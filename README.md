# Romania Power Map

Interactive map of power generation and storage projects in Romania, operating and in development.
Live at https://matand299.github.io/romania-power-map/

- `index.html` – the whole web app (Leaflet map, county panel, filters, pipeline, list view, CSV export)
- `data/plants.json`, `data/counties.json` – data the page loads
- `data/source/` – source spreadsheets and county boundaries
- `scripts/build_data.py` – rebuilds `data/*.json` from the master database

## Data

The map is an interim one, built from two official sources so that no plant appears twice:

- `Puteri-capacitati_24.04.2023_Final_EN_With_Status.xlsx` – the ANRE licensed capacity register (24.04.2023),
  read directly. Plants whose licence had passed its expiry date are kept and marked, since the licence may have
  been renewed. Coordinates come from the master database's copy of the same plant when it has one.
- `entsoe/` – ENTSO-E Transparency Platform, installed capacity per production unit (units of 100 MW and more),
  one file per year. `entsoe_anre_match.csv` says which register plants each unit stands for: a matched unit
  replaces those rows with its current capacity; units built after the register's date are added; capacity listed
  only for later years is shown as under construction.

- `transelectrica/` – Transelectrica (DEN) installed capacity files: `7productie23.xls` (sheet "Stocare", every storage
  installation in the grid) and `7productie12a.xls` (sheet "Fotovoltaice", installed capacity per relevant solar plant).
  All storage installations are added; a solar plant is added only when no solar plant on the map shares a distinctive
  name word or its owner at a capacity within 25%. Plants are placed at the locality their name gives;
  `transelectrica_locations.csv` settles names the other files cannot, with the source.

`Romania_Energy_Projects_Master_Database_2026_EN.xlsx` also holds Transelectrica, distribution-operator and
Global Energy Monitor rows. They are left out (`INCLUDED_SOURCES` in the build script) until each can be checked
against the register.

### Coverage against ANRE's totals

`data/anre_totals.json` holds ANRE's official installed capacity by primary energy type, from its public
"Puteri instalate" report (https://anre.ro/puteri-instalate). Under each technology, the map's "Capacity mix" panel shows
the capacity in operation on the map on 24.04.2023 (field `m23` in `plants.json`) and now, and, when no filter narrows
the map to part of Romania, ANRE's figure and the share of it the map shows. `scripts/fetch_anre_totals.py` refreshes the file.

### Weekly update

`.github/workflows/weekly-data.yml` runs every Monday (or by hand from the Actions tab): it fetches ANRE's totals
(`scripts/fetch_anre_totals.py`) and Transelectrica's installed capacity files (`scripts/fetch_transelectrica.py`),
rebuilds `data/*.json` with `scripts/build_data.py` and commits any change. A source that cannot be fetched keeps its
last good copy.

## Updating the data

Replace or add files in `data/source/`, then run `python3 scripts/build_data.py` and commit.

## Hosting

Served as a static site with GitHub Pages (Settings → Pages → Deploy from branch → `main` / root).
