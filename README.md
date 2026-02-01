# Geodesic Overlay (De-Mercator)

Geodesic Overlay is a lightweight tool for **true-scale geographic comparison**.  
It allows you to overlay outlines from different geographic locations **without Mercator distortion**, preserving **actual distances and relative scale**.

The tool supports both:
- a **static HTML overlay** for quick comparison and sharing, and
- an **interactive web app** where individual outlines can be selected, overlaid, and dragged for visual alignment.

---

## Why this exists

Most web maps (Google Maps, Leaflet, etc.) use **Mercator projection**, which:
- distorts distances and areas,
- makes high-latitude regions appear much larger than they are,
- breaks direct visual comparison of scale.

This project instead uses a **local Azimuthal Equidistant (AEQD) projection**, centered at a user-defined point, so that:
- distances are preserved in meters near the center,
- overlays reflect true relative scale,
- shapes can be compared meaningfully.

---

## Features

- True-scale overlay using **Azimuthal Equidistant projection**
- Config-driven (YAML)
- Supports GeoJSON, Shapefile, GeoPackage (anything GeoPandas can read)
- Category → sub-item selection (e.g. Countries → Japan)
- Interactive draggable overlays
- Optional globe view for geographic context
- Static, self-contained HTML export
- No external services required

---

## Installation

### Recommended (Conda / conda-forge)
```bash
conda create -n geodesic-overlay -c conda-forge
python=3.12 geopandas pyproj shapely pyyaml
conda activate geodesic-overlay
```

This avoids system-level PROJ / GEOS issues.

---

## Data sources

You manually download GeoJSON files and place them in `configs/data/`.

Recommended sources:

- US states and counties  
  https://github.com/codeforamerica/click_that_hood

- Countries and administrative boundaries (Natural Earth)  
  https://github.com/nvkelso/natural-earth-vector

Example downloads:
```bash
curl -L https://raw.githubusercontent.com/codeforamerica/click_that_hood/master/public/data/california-counties.geojson -o configs/data/ca_counties.geojson ;
curl -L https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_countries.geojson -o configs/data/countries.geojson;
```


---

## Controls (interactive app)

- Dropdown: select individual outlines (e.g. Countries → Japan)
- “Add” button: add outline to overlay canvas
- Drag: move outlines to align
- Globe view toggle: show geographic context

---

## Projection details

- Projection: Azimuthal Equidistant (AEQD)
- Units: meters
- Center: user-defined (`projection_center`)
- Distances are accurate near the center point

This tool intentionally does **not** use Mercator projection.

---

## Common pitfalls

- Paths in YAML are relative to `configs/`
- `where` expressions must be valid pandas `.query()` syntax
- Column names (`name`, `ADMIN`, etc.) depend on the dataset
- Very large geometries may benefit from simplification

---

## Roadmap ideas

- Union multiple features into a single outline
- Export aligned overlays as GeoJSON or SVG
- Distance rings (km)
- Snap-to-centroid / snap-to-reference
- Scale bar and numeric distance readout
- Auto-download datasets from URLs

---

## Acknowledgements

- GeoPandas
- PyProj / PROJ
- Natural Earth
- OpenStreetMap
- Code for America

---

## Contact

If you are using this for research or extending it, feel free to open an issue or fork the repository.


