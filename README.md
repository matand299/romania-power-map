# Romania Power Plant Map

Interactive map of licensed electricity generation capacity in Romania, built from the ANRE register (24.04.2023), with licence status per plant.

- `index.html` – the whole web app (Leaflet map, filters, list view, CSV export)
- `data/plants.json`, `data/counties.json` – data the page loads
- `data/source/` – original Excel file and county boundaries
- `scripts/build_data.py` – rebuilds `data/*.json` from the Excel file

## Updating the data

Replace the Excel file in `data/source/`, then run `python3 scripts/build_data.py` and commit.
The script places each plant at its locality using the GeoNames gazetteer (downloaded automatically).

## Hosting

Served as a static site with GitHub Pages (Settings → Pages → Deploy from branch → `main` / root).
