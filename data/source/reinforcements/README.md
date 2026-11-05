# Grid reinforcement works

- `grid-reinforcement-works.xlsx`: 122 grid reinforcement works (lines, transformers, substations), with planning status and year, compared with Transelectrica's PD RET 2026–2035 and PAI 2026. No project data. In Hebrew.
- `titles_en.csv`: the English title of each work. `strings_en.csv`: English for every other Hebrew string the map shows (types, statuses, criteria, findings, notes). The build stops and names any Hebrew string missing here.
- `geometry_spec.py`: for each work, the substations at its ends, in order. `L` = existing line (drawn along the real route from OpenStreetMap; straight if not found), `N` = new line (straight, dashed), `P` = substation point.
- `stations_places.csv`: stations OpenStreetMap does not name, and the town each is placed at (from OSM's places). A blank row means the station could not be found (Banovița, CEE Ialomița, CEE Poiana, Rogojelu); the map says so on the works concerned.
- `osm_grid.json`: OpenStreetMap substations and power plants, lines of 110 kV and more (and lines with no voltage tag), and towns, for Romania. Refresh with `python3 scripts/fetch_osm_grid.py` (Overpass API).

`python3 scripts/build_reinforcements.py` writes `data/reinforcements.json`. How it draws:

- **Substations:** a `stations_places.csv` row first; otherwise the OSM substation with the same name (the highest voltage when several). A station placed at a town moves to the line end its route reaches.
- **Existing lines:** the shortest path over OSM lines of the work's voltage (then any voltage) between the two substations. Gaps of up to 1.5 km between line ends are bridged. A route is rejected, and a straight dotted line drawn instead, when it runs through a third named substation or is more than about twice the straight distance; between two OSM substations, where the source states the length, it must be within −25%/+30% of that length instead.
- **Result (OSM data of 5 Nov 2026):** 91 of 112 sections of existing lines follow an OSM route; 59 of 105 substations are OSM substations, the rest are placed at their town. Where the source gives a length, the drawn route usually comes within a few percent of it (e.g. Tulcea Vest – Tariverde 74.7 km against 74.8; Isaccea – Rahman 55.6 against 55.44).
- **Known gaps:** R085 (Rogojelu – Godinești) is not drawn, since Rogojelu was not found. R108 draws only the 4 of its ~30 lines that are named. R093 states 12.2 km, but OSM's Grădiște and Ișalnița substations are 51 km apart; it is drawn straight and the conflict is left for checking.
