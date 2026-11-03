"""Build the 3D map's base layers from Natural Earth (public domain, https://www.naturalearthdata.com).

Downloads the 1:10m countries, sea, lakes, rivers and populated places, keeps what falls in a box
around Romania, simplifies it and writes data/basemap.json: one GeoJSON FeatureCollection whose
features carry a "layer" property (country, sea, lake, river, city). The map's style colours each
layer, so the look is changed in the theme, not here.

Run from the project root:  python3 scripts/build_basemap.py
"""
import json
import urllib.request
from pathlib import Path

from shapely.geometry import box, mapping, shape

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "basemap.json"
NE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_{}.geojson"
# West, south, east, north: Romania with a margin, so the neighbours and the Black Sea frame it.
BOX = box(18.5, 42.3, 31.5, 49.8)
SIMPLIFY = 0.004  # degrees, about 400 m: finer than the map ever needs at country scale


def load(name):
    print(f"downloading {name}...")
    with urllib.request.urlopen(NE.format(name), timeout=300) as r:
        return json.load(r)["features"]


def clipped(features, layer, keep=lambda p: True, props=lambda p: {}):
    out = []
    for f in features:
        p = f["properties"]
        if not keep(p):
            continue
        geom = shape(f["geometry"])
        if not geom.intersects(BOX):
            continue
        geom = geom.intersection(BOX).simplify(SIMPLIFY, preserve_topology=True)
        if geom.is_empty:
            continue
        out.append({"type": "Feature", "properties": {"layer": layer, **props(p)}, "geometry": mapping(geom)})
    return out


def rounded(obj):
    """Coordinates to 4 decimals (about 10 m), to keep the file small."""
    if isinstance(obj, float):
        return round(obj, 4)
    if isinstance(obj, (list, tuple)):
        return [rounded(x) for x in obj]
    if isinstance(obj, dict):
        return {k: rounded(v) for k, v in obj.items()}
    return obj


def main():
    features = []
    features += clipped(load("admin_0_countries"), "country",
                        props=lambda p: {"name": p["NAME_EN"], "ro": p["ADM0_A3"] == "ROU"})
    features += clipped(load("ocean"), "sea")
    features += clipped(load("lakes"), "lake", props=lambda p: {"name": p.get("name") or ""})
    features += clipped(load("rivers_lake_centerlines"), "river",
                        keep=lambda p: p.get("featurecla") == "River",
                        props=lambda p: {"name": p.get("name_en") or p.get("name") or "", "rank": p.get("scalerank", 10)})
    features += clipped(load("populated_places_simple"), "city",
                        keep=lambda p: p.get("adm0_a3") == "ROU" and (p.get("pop_max") or 0) >= 60000,
                        props=lambda p: {"name": p["name"], "pop": p.get("pop_max") or 0, "capital": p.get("adm0cap") == 1})
    OUT.write_text(json.dumps(rounded({"type": "FeatureCollection", "features": features}),
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    by = {}
    for f in features:
        by[f["properties"]["layer"]] = by.get(f["properties"]["layer"], 0) + 1
    print(f"basemap.json: {OUT.stat().st_size // 1024} KB, {by}")


if __name__ == "__main__":
    main()
