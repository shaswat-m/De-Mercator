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



