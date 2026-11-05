# Grid reinforcement works

- `grid-reinforcement-works.xlsx`: 122 grid reinforcement works (lines, transformers, substations), with planning status and year, compared with Transelectrica's PD RET 2026–2035 and PAI 2026. No project data.
- `geometry_spec.py`: for each work, the substations at its ends, in order. `L` = existing line (draw the real route from OpenStreetMap; straight line if not found), `N` = new line (straight, dashed), `P` = substation point.

Next step: substation coordinates and line routes from OpenStreetMap (Overpass API or the Geofabrik Romania extract), then a "Reinforcements" layer on both maps.
