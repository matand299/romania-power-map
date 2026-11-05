"""Fetch Romania's substations and 110-400 kV lines from OpenStreetMap (Overpass API).

Writes data/source/reinforcements/osm_grid.json, a compact copy that build_reinforcements.py reads:
  substations: [{id, name, names, voltage, operator, lat, lon, r}]  (power=substation and named power=plant)
  places: [{name, place, lat, lon}]  (towns and villages, to place stations OSM does not name)
  lines (110 kV and more, or untagged): [{id, name, ref, voltage, circuits, cables, nodes: [node ids], coords: [[lat, lon], ...]}]

Run again to refresh. Nothing else uses the network.
"""
import json
import math
import pathlib
import sys
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data/source/reinforcements/osm_grid.json"
SERVERS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
UA = "romania-power-map (https://github.com/matand299/romania-power-map)"

Q_STATIONS = """[out:json][timeout:300];
area["ISO3166-1"="RO"][admin_level=2]->.ro;
(nwr["power"="substation"](area.ro); nwr["power"="plant"]["name"](area.ro););
out bb;"""

Q_PLACES = """[out:json][timeout:300];
area["ISO3166-1"="RO"][admin_level=2]->.ro;
node["place"~"^(city|town|village|suburb|quarter|hamlet)$"]["name"](area.ro);
out body;"""

Q_LINES = """[out:json][timeout:600];
area["ISO3166-1"="RO"][admin_level=2]->.ro;
(way["power"="line"](area.ro); way["power"="cable"]["voltage"~"(110000|220000|400000)"](area.ro););
out body geom;"""


def high_voltage(v):
    """Keep lines of 100 kV and more, and lines with no voltage tag (often high-voltage lines nobody tagged)."""
    vals = [x.strip() for x in (v or "").split(";") if x.strip() not in ("", "0")]
    if not vals:
        return True
    nums = [float(x) * (1000 if float(x) < 1000 else 1) for x in vals if x.replace(".", "", 1).isdigit()]
    return not nums or max(nums) >= 100000


def overpass(query):
    body = urllib.parse.urlencode({"data": query}).encode()
    last = None
    for attempt in range(3):
        for url in SERVERS:
            try:
                req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=900) as r:
                    return json.load(r)["elements"]
            except Exception as e:  # try the next server
                last = e
                print(f"  {url}: {e}", file=sys.stderr)
        time.sleep(20 * (attempt + 1))
    raise SystemExit(f"Overpass failed: {last}")


def radius(b, lat):
    if not b:
        return 0
    dy = (b["maxlat"] - b["minlat"]) * 111320
    dx = (b["maxlon"] - b["minlon"]) * 111320 * math.cos(math.radians(lat))
    return math.hypot(dx, dy) / 2


def main():
    print("Substations and plants...")
    stations = []
    for e in overpass(Q_STATIONS):
        t = e.get("tags", {})
        b = e.get("bounds")
        c = {"lat": (b["minlat"] + b["maxlat"]) / 2, "lon": (b["minlon"] + b["maxlon"]) / 2} if b else {"lat": e.get("lat"), "lon": e.get("lon")}
        if c.get("lat") is None:
            continue
        names = [t[k] for k in ("name", "name:ro", "alt_name", "old_name", "short_name", "official_name", "name:en") if t.get(k)]
        if not names and t.get("power") == "substation" and not t.get("voltage"):
            continue
        stations.append({
            "id": f"{e['type'][0]}{e['id']}", "power": t.get("power"), "name": t.get("name", ""), "names": sorted(set(names)),
            "voltage": t.get("voltage", ""), "operator": t.get("operator", ""), "substation": t.get("substation", ""),
            "lat": round(c["lat"], 6), "lon": round(c["lon"], 6),
            # half the diagonal of the outline, metres (0 for a point)
            "r": round(radius(e.get("bounds"), c["lat"])),
        })
    print(f"  {len(stations)}")
    print("Lines...")
    lines = []
    for e in overpass(Q_LINES):
        t = e.get("tags", {})
        if not high_voltage(t.get("voltage")):
            continue
        lines.append({
            "id": e["id"], "power": t.get("power"), "name": t.get("name", ""), "ref": t.get("ref", ""),
            "voltage": t.get("voltage", ""), "circuits": t.get("circuits", ""), "cables": t.get("cables", ""),
            "operator": t.get("operator", ""), "nodes": e["nodes"],
            "coords": [[round(p["lat"], 5), round(p["lon"], 5)] for p in e["geometry"]],
        })
    print(f"  {len(lines)}")
    print("Places...")
    places = [{"name": e["tags"]["name"], "place": e["tags"]["place"], "lat": round(e["lat"], 5), "lon": round(e["lon"], 5)}
              for e in overpass(Q_PLACES)]
    print(f"  {len(places)}")
    OUT.write_text(json.dumps({"fetched": time.strftime("%Y-%m-%d"), "source": "OpenStreetMap contributors (ODbL), via the Overpass API",
                               "substations": stations, "lines": lines, "places": places}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
