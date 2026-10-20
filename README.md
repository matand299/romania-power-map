# Romania Power Map

Interactive map of power generation and storage projects in Romania, operating and in development.
Live at https://matand299.github.io/romania-power-map/

- `index.html` – the whole web app (Leaflet map, county panel, filters, pipeline, list view, CSV export)
- `data/plants.json`, `data/counties.json` – data the page loads
- `data/source/` – source spreadsheets and county boundaries
- `scripts/build_data.py` – rebuilds `data/*.json` from the master database

## Data

`Romania_Energy_Projects_Master_Database_2026_EN.xlsx` combines the ANRE licensed capacity register (2023),
Transelectrica's connection annexes, the distribution operators' annexes (DEER, Rețele Electrice, DEO) and
Global Energy Monitor rows. The build script removes subtotal rows and cross-source duplicates, converts
kW values recorded as MW, normalises technologies, stages and counties, and places rows that carry a
placeholder location using the GeoNames gazetteer. The earlier ANRE export supplies licence dates.

## Updating the data

Replace the master Excel in `data/source/`, then run `python3 scripts/build_data.py` and commit.

## Hosting

Served as a static site with GitHub Pages (Settings → Pages → Deploy from branch → `main` / root).
