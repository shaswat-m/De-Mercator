#!/usr/bin/env python3
"""
generate_overlay_html.py

Reads a YAML config of locations (local GIS files), projects them into a common
Azimuthal Equidistant (AEQD) plane in meters (near-true distances around a chosen center),
and writes a self-contained HTML with:
- True-scale overlay (SVG, draggable not required here)
- Optional globe view (Leaflet) showing where the locations are on Earth

Usage:
  python generate_overlay_html.py --config config.yaml --out overlay.html

Dependencies:
  pip install geopandas shapely pyproj pyyaml
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import geopandas as gpd
import yaml
from pyproj import CRS


def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _ensure_wgs84(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.crs is None:
        # Best effort: assume data is WGS84 if CRS missing.
        gdf = gdf.set_crs(epsg=4326)
    return gdf.to_crs(epsg=4326)


def _pick_center(config: Dict[str, Any], wgs_layers: List[gpd.GeoDataFrame]) -> Tuple[float, float]:
    """
    Returns (lat0, lon0) for AEQD center.
    Priority:
      1) config["projection_center"] = {lat: .., lon: ..}
      2) centroid of first layer (in WGS84)
    """
    pc = config.get("projection_center")
    if isinstance(pc, dict) and "lat" in pc and "lon" in pc:
        return float(pc["lat"]), float(pc["lon"])

    # Centroid of first layer
    first = wgs_layers[0]
    # Use unary_union centroid (robust for multi-features)
    c = first.geometry.unary_union.centroid
    return float(c.y), float(c.x)


def _make_aeqd_crs(lat0: float, lon0: float) -> CRS:
    # Azimuthal Equidistant projection centered at (lat0, lon0)
    proj4 = f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} +datum=WGS84 +units=m +no_defs"
    return CRS.from_proj4(proj4)


def _read_location(loc: Dict[str, Any], config_path: Path) -> gpd.GeoDataFrame:
    """
    Location dict fields supported:
      - id: string (required)
      - name: string (optional)
      - path: file path (required)
      - where: optional filter (pandas query string) applied after read
      - layer: optional layer name (for multi-layer files like GPKG)
    """
    #path = Path(loc["path"]).expanduser()
    cfg_dir = Path(config_path).resolve().parent
    path = (cfg_dir / loc["path"]).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Location '{loc.get('id')}' path not found: {path}")

    layer = loc.get("layer")
    if layer is not None:
        gdf = gpd.read_file(path, layer=layer)
    else:
        gdf = gpd.read_file(path)

    where = loc.get("where")
    if where:
        gdf = gdf.query(where)

    if gdf.empty:
        raise ValueError(f"Location '{loc.get('id')}' produced an empty GeoDataFrame after reading/filtering.")

    # Keep only geometry
    gdf = gdf[[c for c in gdf.columns if c == "geometry"]].copy()
    return gdf


def _to_feature_collection(gdf: gpd.GeoDataFrame, props: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert GeoDataFrame geometry to GeoJSON FeatureCollection with uniform properties.
    """
    features = []
    for geom in gdf.geometry:
        if geom is None or geom.is_empty:
            continue
        features.append({
            "type": "Feature",
            "properties": dict(props),
            "geometry": json.loads(gpd.GeoSeries([geom]).to_json())["features"][0]["geometry"],
        })
    return {"type": "FeatureCollection", "features": features}


def _make_html(payload: Dict[str, Any]) -> str:
    # Self-contained HTML with:
    # - overlay SVG using d3 geoIdentity().fitSize to project meters coords into screen space
    # - Leaflet globe view in EPSG:3857 (only for context, not for "true scale" overlay)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{payload["title"]}</title>
<style>
  body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; margin: 0; }}
  header {{ padding: 12px 16px; border-bottom: 1px solid #ddd; }}
  header h1 {{ font-size: 16px; margin: 0 0 4px 0; }}
  header .meta {{ color: #555; font-size: 12px; }}
  .wrap {{ display: grid; grid-template-columns: 1fr; gap: 12px; padding: 12px; }}
  .panel {{ border: 1px solid #ddd; border-radius: 10px; overflow: hidden; }}
  .panel .bar {{ display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; border-bottom: 1px solid #eee; background: #fafafa; }}
  .panel .bar .left {{ font-weight: 600; font-size: 13px; }}
  .panel .bar .right {{ font-size: 12px; color: #444; display: flex; gap: 10px; align-items: center; }}
  .panel .content {{ padding: 0; }}
  #overlay {{ width: 100%; height: 70vh; }}
  #map {{ width: 100%; height: 55vh; display: none; }}
  .legend {{ display: flex; flex-wrap: wrap; gap: 10px; padding: 10px 12px; border-top: 1px solid #eee; background: #fff; }}
  .chip {{ display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: #222; }}
  .dot {{ width: 10px; height: 10px; border-radius: 999px; display: inline-block; }}
</style>
</head>
<body>
<header>
  <h1>{payload["title"]}</h1>
  <div class="meta">
    True-scale overlay uses an Azimuthal Equidistant projection (meters) centered at
    ({payload["center"]["lat"]:.6f}, {payload["center"]["lon"]:.6f}). Globe view is for context.
  </div>
</header>

<div class="wrap">
  <div class="panel">
    <div class="bar">
      <div class="left">True-scale overlay (dragging not enabled in this static view)</div>
      <div class="right">
        <label><input id="toggleGlobe" type="checkbox"/> Globe view</label>
      </div>
    </div>
    <div class="content">
      <svg id="overlay" viewBox="0 0 1200 800" preserveAspectRatio="xMidYMid meet"></svg>
      <div id="map"></div>
    </div>
    <div class="legend" id="legend"></div>
  </div>
</div>

<!-- D3 (minified) -->
<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
<!-- Leaflet -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js"></script>

<script>
const DATA = {json.dumps(payload, ensure_ascii=False)};

const svg = d3.select("#overlay");
const width = 1200, height = 800;

function renderOverlay() {{
  svg.selectAll("*").remove();

  const projected = DATA.projected; // meters coords in GeoJSON
  const projection = d3.geoIdentity().reflectY(true).fitSize([width, height], projected);
  const path = d3.geoPath(projection);

  // draw each location as its own group for clarity
  const byId = d3.group(projected.features, d => d.properties.id);

  for (const [id, feats] of byId) {{
    const color = feats[0].properties.color || "#111";
    svg.append("g")
      .attr("data-id", id)
      .selectAll("path")
      .data(feats)
      .enter()
      .append("path")
      .attr("d", d => path(d))
      .attr("fill", "none")
      .attr("stroke", color)
      .attr("stroke-width", 2)
      .attr("opacity", 0.9);
  }}
}}

function renderLegend() {{
  const legend = d3.select("#legend");
  legend.selectAll("*").remove();
  DATA.locations.forEach(loc => {{
    const chip = legend.append("div").attr("class", "chip");
    chip.append("span").attr("class", "dot").style("background", loc.color);
    chip.append("span").text(loc.name || loc.id);
  }});
}}

let map, mapLayers = [];

function initMap() {{
  if (map) return;
  map = L.map("map", {{ preferCanvas: true }});
  L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }}).addTo(map);

  // Add WGS84 layers
  const bounds = [];
  DATA.locations.forEach(loc => {{
    const layer = L.geoJSON(loc.wgs84, {{
      style: () => ({{ color: loc.color, weight: 2, fillOpacity: 0.0 }})
    }}).addTo(map);
    mapLayers.push(layer);
    layer.getLayers().forEach(l => {{
      if (l.getBounds) bounds.push(l.getBounds());
    }});
  }});

  if (bounds.length) {{
    const b = bounds.reduce((acc, bb) => acc.extend(bb), bounds[0]);
    map.fitBounds(b.pad(0.15));
  }} else {{
    map.setView([DATA.center.lat, DATA.center.lon], 2);
  }}
}}

function setGlobeVisible(on) {{
  const mapEl = document.getElementById("map");
  const svgEl = document.getElementById("overlay");
  mapEl.style.display = on ? "block" : "none";
  svgEl.style.display = on ? "none" : "block";
  if (on) {{
    initMap();
    setTimeout(() => map.invalidateSize(), 50);
  }}
}}

document.getElementById("toggleGlobe").addEventListener("change", (e) => {{
  setGlobeVisible(e.target.checked);
}});

renderOverlay();
renderLegend();
</script>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="Path to YAML config")
    ap.add_argument("--out", required=True, help="Output HTML file")
    args = ap.parse_args()

    cfg_path = Path(args.config)
    out_path = Path(args.out)

    cfg = _load_yaml(cfg_path)
    title = cfg.get("title", "geodesic-overlay")

    locs = cfg.get("locations")
    if not isinstance(locs, list) or not locs:
        raise ValueError("Config must contain a non-empty 'locations:' list.")

    # Load layers
    raw_layers = []
    for loc in locs:
        if "id" not in loc or "path" not in loc:
            raise ValueError("Each location must have at least: id, path")
        cfg_path = Path(args.config)
        raw_layers.append(_read_location(loc, cfg_path))

    # Convert to WGS84
    wgs_layers = [_ensure_wgs84(g) for g in raw_layers]

    # Choose AEQD center and project all layers to meters
    lat0, lon0 = _pick_center(cfg, wgs_layers)
    aeqd = _make_aeqd_crs(lat0, lon0)

    colors = cfg.get("colors") or [
        "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
        "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    ]

    locations_payload = []
    projected_features = []
    for i, (loc, g_wgs) in enumerate(zip(locs, wgs_layers)):
        g_m = g_wgs.to_crs(aeqd)
        color = loc.get("color") or colors[i % len(colors)]
        name = loc.get("name") or loc["id"]

        proj_fc = _to_feature_collection(g_m, {"id": loc["id"], "name": name, "color": color})
        wgs_fc = _to_feature_collection(g_wgs, {"id": loc["id"], "name": name, "color": color})

        projected_features.extend(proj_fc["features"])
        locations_payload.append({
            "id": loc["id"],
            "name": name,
            "color": color,
            "wgs84": wgs_fc,
        })

    payload = {
        "title": title,
        "center": {"lat": lat0, "lon": lon0},
        "projected": {"type": "FeatureCollection", "features": projected_features},
        "locations": locations_payload,
    }

    html = _make_html(payload)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()

