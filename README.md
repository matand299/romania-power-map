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
  installation in the grid) and `7productie12a.xls` (sheets "Fotovoltaice" and "Eolian", installed capacity per relevant solar and wind plant).
  All storage installations are added. A solar or wind plant counts as already on the map when a plant of that type
  there shares a distinctive name word or its owner at a capacity within 25%; register rows that are the same plant in
  stages or before an extension are replaced by Transelectrica's figure; otherwise the plant is added. Plants are placed at the locality their name gives;
  `transelectrica_locations.csv` settles names the other files cannot, with the source.

`Romania_Energy_Projects_Master_Database_2026_EN.xlsx` also holds Transelectrica, distribution-operator and
Global Energy Monitor rows. They are left out (`INCLUDED_SOURCES` in the build script) until each can be checked
against the register.

### Official totals

`data/official_totals.json` holds ANRE licensed capacity by fuel as Transelectrica tabulates it ("Pi licenta ANRE",
sheet "Sheet1" of `7productie23.xls`) now, and on 01.05.2023 from Transelectrica's archive
(`puteri-instalate-2023-05-01.xls`, unchanged since 01.03.2023, so it holds on the register's date). Under each
technology the "Capacity mix" panel shows Romania's official capacity now, its change since 2023, and the share of it
on the map. Each plant in `plants.json` also carries `m23`, its capacity on the map's 2023 base (24.04.2023).

### Weekly update

`.github/workflows/weekly-data.yml` runs every Monday (or by hand from the Actions tab): it fetches Transelectrica's installed capacity files (`scripts/fetch_transelectrica.py`), rebuilds `data/*.json` with `scripts/build_data.py` and commits any change. If the files cannot be fetched, the last good
copy stays.

## Updating the data

Replace or add files in `data/source/`, then run `python3 scripts/build_data.py` and commit.

## Hosting

Served as a static site with GitHub Pages (Settings → Pages → Deploy from branch → `main` / root).
