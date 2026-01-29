#!/usr/bin/env python3
"""
run_overlay_app.py

Launches a local web app for interactively overlaying selected locations:
- dropdown to choose a location
- "+" add multiple layers
- each added shape becomes visible and draggable (SVG)
- optional toggle to show globe view (Leaflet), default is overlay canvas

Usage:
  python run_overlay_app.py --config config.yaml --port 8000

Dependencies:
  pip install geopandas shapely pyproj pyyaml
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import threading
import webbrowser
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, List, Tuple

import geopandas as gpd
import yaml
from pyproj import CRS


def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _ensure_wgs84(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=4326)
    return gdf.to_crs(epsg=4326)


def _pick_center(config: Dict[str, Any], wgs_layers: List[gpd.GeoDataFrame]) -> Tuple[float, float]:
    pc = config.get("projection_center")
    if isinstance(pc, dict) and "lat" in pc and "lon" in pc:
        return float(pc["lat"]), float(pc["lon"])
    c = wgs_layers[0].geometry.unary_union.centroid
    return float(c.y), float(c.x)


def _make_aeqd_crs(lat0: float, lon0: float) -> CRS:
    proj4 = f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} +datum=WGS84 +units=m +no_defs"
    return CRS.from_proj4(proj4)


def _read_location(loc: Dict[str, Any], config_path: Path) -> gpd.GeoDataFrame:
    #path = Path(loc["path"]).expanduser()
    cfg_dir = Path(config_path).resolve().parent
    path = (cfg_dir / loc["path"]).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Location '{loc.get('id')}' path not found: {path}")

    layer = loc.get("layer")
    gdf = gpd.read_file(path, layer=layer) if layer is not None else gpd.read_file(path)

    where = loc.get("where")
    if where:
        gdf = gdf.query(where)

    if gdf.empty:
        raise ValueError(f"Location '{loc.get('id')}' produced an empty GeoDataFrame after reading/filtering.")

    gdf = gdf[[c for c in gdf.columns if c == "geometry"]].copy()
    return gdf


def _geom_to_geojson_feature_collection(gdf: gpd.GeoDataFrame, props: Dict[str, Any]) -> Dict[str, Any]:
    feats = []
    for geom in gdf.geometry:
        if geom is None or geom.is_empty:
            continue
        geom_json = json.loads(gpd.GeoSeries([geom]).to_json())["features"][0]["geometry"]
        feats.append({"type": "Feature", "properties": dict(props), "geometry": geom_json})
    return {"type": "FeatureCollection", "features": feats}


def _write_app_files(out_dir: Path, payload: Dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "data").mkdir(parents=True, exist_ok=True)

    (out_dir / "data" / "locations.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )

    (out_dir / "index.html").write_text(_APP_HTML, encoding="utf-8")


_APP_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>geodesic-overlay app</title>
<style>
  body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; margin: 0; }
  header { padding: 12px 16px; border-bottom: 1px solid #ddd; display:flex; align-items:center; justify-content:space-between; gap:12px; }
  header .title { font-weight: 650; }
  header .controls { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
  .wrap { padding: 12px; display:grid; gap:12px; }
  .panel { border: 1px solid #ddd; border-radius: 10px; overflow:hidden; }
  .bar { padding: 10px 12px; border-bottom: 1px solid #eee; background:#fafafa; display:flex; justify-content:space-between; align-items:center; }
  .bar .left { font-weight: 600; font-size: 13px; }
  .bar .right { display:flex; align-items:center; gap:10px; font-size: 12px; color:#444; }
  #overlayWrap { width:100%; height: 75vh; }
  #overlay { width:100%; height:100%; display:block; }
  #map { width:100%; height: 60vh; display:none; }
  .pill { font-size:12px; padding:3px 8px; border:1px solid #ddd; border-radius:999px; background:#fff; }
  select, button { font-size: 13px; padding: 6px 8px; }
  button { cursor:pointer; }
  .layerList { display:flex; flex-wrap:wrap; gap:8px; padding: 10px 12px; border-top: 1px solid #eee; background:#fff; }
  .layerChip { display:flex; align-items:center; gap:8px; border:1px solid #ddd; border-radius:999px; padding:6px 10px; font-size:12px; }
  .dot { width:10px; height:10px; border-radius:999px; display:inline-block; }
  .layerChip button { font-size:12px; padding: 2px 6px; }
</style>
</head>
<body>

<header>
  <div class="title">Interactive overlay (true-scale plane + optional globe)</div>
  <div class="controls">
    <label class="pill">Location:
      <select id="locSelect"></select>
    </label>
    <button id="addBtn">+ Add</button>
    <label class="pill"><input type="checkbox" id="globeToggle"/> Globe view</label>
    <span class="pill" id="centerInfo"></span>
  </div>
</header>

<div class="wrap">
  <div class="panel">
    <div class="bar">
      <div class="left">Overlay canvas (drag outlines to align)</div>
      <div class="right">
        <span>Tip: add multiple, then drag each layer</span>
      </div>
    </div>

    <div id="overlayWrap">
      <svg id="overlay" viewBox="0 0 1200 800" preserveAspectRatio="xMidYMid meet"></svg>
      <div id="map"></div>
    </div>

    <div class="layerList" id="layerList"></div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js"></script>

<script>
let DATA;
let map, baseTile;
let activeLayers = []; // {id, name, color, projected, wgs84, tx, ty, g}

const svg = d3.select("#overlay");
const W = 1200, H = 800;

function uniqId(prefix="layer") {
  return prefix + "_" + Math.random().toString(16).slice(2);
}

async function init() {
  const res = await fetch("./data/locations.json");
  DATA = await res.json();

  document.getElementById("centerInfo").textContent =
    `AEQD center: (${DATA.center.lat.toFixed(4)}, ${DATA.center.lon.toFixed(4)})`;

  const sel = document.getElementById("locSelect");
  DATA.locations.forEach((loc, idx) => {
    const opt = document.createElement("option");
    opt.value = loc.id;
    opt.textContent = loc.name || loc.id;
    sel.appendChild(opt);
  });

  document.getElementById("addBtn").addEventListener("click", addSelected);
  document.getElementById("globeToggle").addEventListener("change", (e) => setGlobeVisible(e.target.checked));

  render();
}

function getLocById(id) {
  return DATA.locations.find(x => x.id === id);
}

function addSelected() {
  const id = document.getElementById("locSelect").value;
  const loc = getLocById(id);
  if (!loc) return;

  // allow duplicates, but make unique layer instance
  const instId = uniqId(id);
  activeLayers.push({
    instId,
    id: loc.id,
    name: loc.name || loc.id,
    color: loc.color,
    projected: loc.projected,
    wgs84: loc.wgs84,
    tx: 0,
    ty: 0,
  });

  render();
}

function removeLayer(instId) {
  activeLayers = activeLayers.filter(l => l.instId !== instId);
  render();
}

function renderLayerList() {
  const wrap = d3.select("#layerList");
  wrap.selectAll("*").remove();

  activeLayers.forEach(l => {
    const chip = wrap.append("div").attr("class","layerChip");
    chip.append("span").attr("class","dot").style("background", l.color);
    chip.append("span").text(l.name);
    chip.append("button").text("Remove").on("click", () => removeLayer(l.instId));
  });
}

function renderOverlay() {
  svg.selectAll("*").remove();

  if (activeLayers.length === 0) return;

  // Fit projection to *all* active layers combined so you always see everything.
  const allFeatures = activeLayers.flatMap(l => l.projected.features.map(f => ({
    ...f,
    properties: {...f.properties, __instId: l.instId, __color: l.color}
  })));
  const fc = {type:"FeatureCollection", features: allFeatures};

  const projection = d3.geoIdentity().reflectY(true).fitSize([W, H], fc);
  const path = d3.geoPath(projection);

  // One group per layer (draggable)
  activeLayers.forEach(layer => {
    const g = svg.append("g")
      .attr("data-inst-id", layer.instId)
      .attr("transform", `translate(${layer.tx}, ${layer.ty})`);

    g.selectAll("path")
      .data(layer.projected.features)
      .enter()
      .append("path")
      .attr("d", d => path(d))
      .attr("fill","none")
      .attr("stroke", layer.color)
      .attr("stroke-width", 2)
      .attr("opacity", 0.9);

    // drag behavior
    g.call(d3.drag()
      .on("start", () => {})
      .on("drag", (event) => {
        layer.tx += event.dx;
        layer.ty += event.dy;
        g.attr("transform", `translate(${layer.tx}, ${layer.ty})`);
      })
    );

    layer.g = g;
  });
}

function initMapIfNeeded() {
  if (map) return;
  map = L.map("map", { preferCanvas: true });
  baseTile = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19, attribution: '&copy; OpenStreetMap contributors'
  }).addTo(map);
  map.setView([DATA.center.lat, DATA.center.lon], 2);
}

let leafletLayers = [];

function renderMap() {
  initMapIfNeeded();
  leafletLayers.forEach(l => l.remove());
  leafletLayers = [];

  if (activeLayers.length === 0) {
    map.setView([DATA.center.lat, DATA.center.lon], 2);
    return;
  }

  const bounds = [];
  activeLayers.forEach(layer => {
    const gl = L.geoJSON(layer.wgs84, {
      style: () => ({ color: layer.color, weight: 2, fillOpacity: 0.0 })
    }).addTo(map);
    leafletLayers.push(gl);
    gl.getLayers().forEach(x => {
      if (x.getBounds) bounds.push(x.getBounds());
    });
  });

  if (bounds.length) {
    const b = bounds.reduce((acc, bb) => acc.extend(bb), bounds[0]);
    map.fitBounds(b.pad(0.15));
  }
}

function setGlobeVisible(on) {
  const mapEl = document.getElementById("map");
  const svgEl = document.getElementById("overlay");
  mapEl.style.display = on ? "block" : "none";
  svgEl.style.display = on ? "none" : "block";
  if (on) {
    renderMap();
    setTimeout(() => map.invalidateSize(), 50);
  }
}

function render() {
  renderLayerList();
  renderOverlay();
  if (document.getElementById("globeToggle").checked) renderMap();
}

init();
</script>

</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="Path to YAML config")
    ap.add_argument("--port", type=int, default=8000, help="Port to serve the app")
    ap.add_argument("--outdir", default="_overlay_app", help="Directory to write the app assets")
    args = ap.parse_args()

    cfg = _load_yaml(Path(args.config))
    locs = cfg.get("locations")
    if not isinstance(locs, list) or not locs:
        raise ValueError("Config must contain a non-empty 'locations:' list.")

    raw_layers = []
    for loc in locs:
        if "id" not in loc or "path" not in loc:
            raise ValueError("Each location must have at least: id, path")
        cfg_path = Path(args.config)
        raw_layers.append(_read_location(loc, cfg_path))

    wgs_layers = [_ensure_wgs84(g) for g in raw_layers]
    lat0, lon0 = _pick_center(cfg, wgs_layers)
    aeqd = _make_aeqd_crs(lat0, lon0)

    colors = cfg.get("colors") or [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
        "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    ]

    locations_payload = []
    for i, (loc, g_wgs) in enumerate(zip(locs, wgs_layers)):
        g_m = g_wgs.to_crs(aeqd)

        color = loc.get("color") or colors[i % len(colors)]
        name = loc.get("name") or loc["id"]

        projected_fc = _geom_to_geojson_feature_collection(g_m, {"id": loc["id"], "name": name})
        wgs_fc = _geom_to_geojson_feature_collection(g_wgs, {"id": loc["id"], "name": name})

        locations_payload.append({
            "id": loc["id"],
            "name": name,
            "color": color,
            "projected": projected_fc,
            "wgs84": wgs_fc,
        })

    payload = {
        "center": {"lat": lat0, "lon": lon0},
        "locations": locations_payload,
    }

    out_dir = Path(args.outdir)
    _write_app_files(out_dir, payload)

    # Serve out_dir
    os.chdir(out_dir)

    server = ThreadingHTTPServer(("0.0.0.0", args.port), SimpleHTTPRequestHandler)

    url = f"http://localhost:{args.port}/index.html"
    print(f"Serving: {url}")
    webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

