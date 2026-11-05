"""Build data/reinforcements.json: grid reinforcement works, with the lines and substations they touch.

Inputs (data/source/reinforcements/):
  grid-reinforcement-works.xlsx  the works (sheet 1) and their comparison with Transelectrica's plans (sheet 2), in Hebrew.
  titles_en.csv, strings_en.csv  English for the work titles and for every other Hebrew string the page shows.
  geometry_spec.py               for each work, its stations in order: L = existing line (route from OSM),
                                 N = new line (straight), P = substation point(s).
  osm_grid.json                  OpenStreetMap substations, 110-400 kV lines and towns (scripts/fetch_osm_grid.py).
  stations_places.csv            stations OpenStreetMap does not name: the town each is placed at (blank = not found).

Placing a station: a stations_places.csv row wins; otherwise the OSM substation of the same name (highest voltage).
Routing an existing line: shortest path over OSM lines of the work's voltage (then any voltage) between the line ends
at the two stations. A station placed at a town attaches to line ends within 5 km, and moves to the line end the route
used. Gaps in the OSM lines (up to 1.5 km between line ends, away from substations) are bridged at double cost.
A route is rejected, and a straight line drawn instead (marked as not routed), when it runs through a third named
substation, or when it is more than about twice the straight distance; between two OSM substations, where the
source states the line's length, the route must instead be within -25%/+30% of that length.

Run from the project root:  python3 scripts/build_reinforcements.py
"""
import csv
import heapq
import importlib.util
import json
import math
import re
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "source" / "reinforcements"
OUT = ROOT / "data" / "reinforcements.json"

TOWN_ATTACH_M = 5000
TOWN_TAP_M = 2500
TAP_COST_M = 3000
GAP_M = 1500
GAP_COST = 2.0  # a bridged gap costs double, so a mapped line is preferred
MAX_DETOUR = 2.2


def load_spec():
    spec = importlib.util.spec_from_file_location("geometry_spec", SRC / "geometry_spec.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.S, m.NOTES


def read_csv(name):
    with open(SRC / name, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def ascii_fold(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def norm_station(s):
    s = ascii_fold(s)
    s = re.sub(r"\d+(\s*/\s*\d+)*\s*kv", " ", s)
    s = re.sub(r"\b(statia|statie|statiei|stația|substation|power station|de transformare|electrica|ps|st|ste)\b", " ", s)
    s = re.sub(r"[^a-z]+", " ", s)
    return " ".join(s.split())


def dist_m(a, b):
    dy = (a[0] - b[0]) * 111320
    dx = (a[1] - b[1]) * 111320 * math.cos(math.radians((a[0] + b[0]) / 2))
    return math.hypot(dx, dy)


def polyline_m(c):
    return sum(dist_m(c[i], c[i + 1]) for i in range(len(c) - 1))


def simplify(pts, tol_m=25):
    """Douglas-Peucker in metres (local flat projection)."""
    if len(pts) < 3:
        return pts
    k = math.cos(math.radians(pts[0][0]))
    xy = [(p[1] * 111320 * k, p[0] * 111320) for p in pts]
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        (x1, y1), (x2, y2) = xy[i], xy[j]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy) or 1e-9
        best, bi = -1, -1
        for m in range(i + 1, j):
            d = abs(dy * (xy[m][0] - x1) - dx * (xy[m][1] - y1)) / L
            if d > best:
                best, bi = d, m
        if best > tol_m:
            keep[bi] = True
            stack += [(i, bi), (bi, j)]
    return [p for p, k_ in zip(pts, keep) if k_]


class Grid:
    """Spatial hash of points for radius queries."""

    def __init__(self, cell=0.05):
        self.cell, self.cells = cell, defaultdict(list)

    def add(self, lat, lon, item):
        self.cells[(int(lat // self.cell), int(lon // self.cell))].append((lat, lon, item))

    def near(self, lat, lon, r_m):
        n = int(r_m / (111320 * self.cell)) + 1
        ci, cj = int(lat // self.cell), int(lon // self.cell)
        for i in range(ci - n, ci + n + 1):
            for j in range(cj - n, cj + n + 1):
                for la, lo, it in self.cells.get((i, j), ()):
                    d = dist_m((lat, lon), (la, lo))
                    if d <= r_m:
                        yield d, it


# ---------------------------------------------------------------- the line network

def kv_set(v):
    """Voltages of a line as strings in volts ("110000"); 380 kV counts as 400, 230 kV as 220. Empty = untagged."""
    out = set()
    for x in (v or "").split(";"):
        x = x.strip()
        try:
            n = float(x)
        except ValueError:
            continue
        if n <= 0:
            continue
        n = n * 1000 if n < 1000 else n
        # 380 and 230 kV are other names for the 400 and 220 kV grids; near misses (222 kV) are typing slips.
        n = {380000: 400000, 230000: 220000}.get(int(n), int(n))
        n = next((v for v in (110000, 220000, 400000) if abs(n - v) <= 0.05 * v), n)
        out.add(str(n))
    return out


UNTAGGED_COST = 1.3  # a line with no voltage tag may stand in for any voltage, at a little extra cost


def fits(cls, classes):
    return classes is None or not cls or bool(cls & classes)


class Network:
    def __init__(self, osm):
        self.coord = {}
        self.adj = defaultdict(list)  # node -> [(node, metres, class)]
        self.ends = Grid()
        self.nodes = Grid()
        subs = self.subs = Grid()
        for s in osm["substations"]:
            subs.add(s["lat"], s["lon"], s)
        ends = []
        for line in osm["lines"]:
            cls = kv_set(line["voltage"])
            for n, c in zip(line["nodes"], line["coords"]):
                self.coord[n] = tuple(c)
            for a, b in zip(line["nodes"], line["nodes"][1:]):
                d = dist_m(self.coord[a], self.coord[b])
                self.adj[a].append((b, d, frozenset(cls)))
                self.adj[b].append((a, d, frozenset(cls)))
            for n in line["nodes"][1:-1]:
                self.nodes.add(*self.coord[n], (n, frozenset(cls)))
            for n in (line["nodes"][0], line["nodes"][-1]):
                self.ends.add(*self.coord[n], (n, frozenset(cls)))
                ends.append((n, frozenset(cls)))
        # Bridge small mapping gaps between line ends, but not inside or next to a substation,
        # where separate lines end side by side.
        bridged = 0
        for n, cls in ends:
            c = self.coord[n]
            if any(d <= s["r"] + 300 for d, s in subs.near(*c, 1500)):
                continue
            for d, (m, mcls) in self.ends.near(*c, GAP_M):
                if m != n and (not cls or not mcls or cls & mcls) and not any(x == m for x, _, _ in self.adj[n]):
                    both = (cls & mcls) if cls and mcls else (cls or mcls)
                    self.adj[n].append((m, d * GAP_COST, both))
                    self.adj[m].append((n, d * GAP_COST, both))
                    bridged += 1
        self.bridged = bridged // 2

    def attach(self, st, classes, other):
        """Line nodes a station connects to, with a cost in metres: [(node, cost)].

        An OSM substation takes the line ends at its outline. A station placed at a town takes line ends within
        TOWN_ATTACH_M, paying the distance (so the nearest wins), or failing that a line passing within
        TOWN_TAP_M (a tap, for a station on a through line), paying extra. Nodes nearer the other end are skipped.
        """
        here, there = (st["lat"], st["lon"]), (other["lat"], other["lon"])
        ok = lambda d, n, cls: fits(cls, classes) and d < dist_m(self.coord[n], there)
        if st["precision"] != "town":
            r = max(st.get("r", 0), 100) + 500
            return [(n, d * 0.2) for d, (n, cls) in self.ends.near(*here, r) if ok(d, n, cls)]
        out = [(n, d) for d, (n, cls) in self.ends.near(*here, TOWN_ATTACH_M) if ok(d, n, cls)]
        out += [(n, d + TAP_COST_M) for d, (n, cls) in self.nodes.near(*here, TOWN_TAP_M) if ok(d, n, cls)]
        return out

    def passes_through(self, path, a, b, chain=()):
        """A named 110 kV-or-more substation the path runs through, other than its ends and its own chain's stations."""
        ends = [(a["lat"], a["lon"]), (b["lat"], b["lon"])]
        for c in path[1:-1]:
            for d, s in self.subs.near(*c, 1200):
                if (s["power"] == "substation" and s["name"] and d <= s["r"] + 100 and kv_set(s["voltage"]) & {"110000", "220000", "400000"}
                        and not any(norm_station(x) == norm_station(n) for x in s["names"] for n in chain)
                        and all(dist_m((s["lat"], s["lon"]), e) > 1500 for e in ends)):
                    return s["name"]
        return None

    def route(self, a, b, classes):
        src, dst = self.attach(a, classes, b), dict(self.attach(b, classes, a))
        if not src or not dst:
            return None
        dist, prev, heap = {}, {}, []
        for n, d in src:
            if d < dist.get(n, 1e18):
                dist[n] = d
                prev[n] = None
                heapq.heappush(heap, (dist[n], n))
        best, best_n = 1e18, None
        while heap:
            d, n = heapq.heappop(heap)
            if d > dist.get(n, 1e18) or d >= best:
                continue
            if n in dst:
                tot = d + dst[n]
                if tot < best:
                    best, best_n = tot, n
            for m, dm, cls in self.adj[n]:
                if not fits(cls, classes):
                    continue
                nd = d + (dm * UNTAGGED_COST if classes is not None and not cls else dm)
                if nd < dist.get(m, 1e18):
                    dist[m], prev[m] = nd, n
                    heapq.heappush(heap, (nd, m))
        if best_n is None:
            return None
        path, n = [], best_n
        while n is not None:
            path.append(n)
            n = prev[n]
        path.reverse()
        return [self.coord[n] for n in path]


# ---------------------------------------------------------------- stations

def resolve_stations(names, osm, places):
    by_norm = defaultdict(list)
    for s in osm["substations"]:
        for n in s["names"]:
            by_norm[norm_station(n)].append(s)
    rank = lambda s: (s["power"] == "substation", max([int(v) for v in kv_set(s["voltage"]) if v.isdigit()] or [0]))
    out = {}
    for name in sorted(names):
        p = places.get(name)
        if p is not None:
            if not p["lat"]:
                out[name] = None
                continue
            out[name] = {"name": name, "lat": float(p["lat"]), "lon": float(p["lon"]), "precision": "town",
                         "place": p["place"], "note": p["note"]}
            continue
        cands = by_norm.get(norm_station(name), [])
        if not cands:
            out[name] = None
            continue
        s = max(cands, key=rank)
        out[name] = {"name": name, "lat": s["lat"], "lon": s["lon"], "precision": "osm", "osm": s["id"], "r": s["r"],
                     "osm_name": s["name"], "kv": "/".join(str(int(v) // 1000) for v in sorted(kv_set(s["voltage"]), key=lambda v: -int(v)) if v.isdigit())}
    return out


# ---------------------------------------------------------------- counties

def load_counties():
    cd = json.loads((ROOT / "data" / "counties.json").read_text(encoding="utf-8"))
    polys = []
    for f in cd["features"]:
        g = f["geometry"]
        rings = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        polys.append((f["properties"]["name"], [r[0] for r in rings]))
    return polys


def county_of(lat, lon, polys):
    for name, rings in polys:
        for ring in rings:
            inside = False
            for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
                if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
                    inside = not inside
            if inside:
                return name
    return None


# ---------------------------------------------------------------- works

def main():
    S, NOTES = load_spec()
    osm = json.loads((SRC / "osm_grid.json").read_text(encoding="utf-8"))
    places = {r["station"]: r for r in read_csv("stations_places.csv")}
    titles = {r["id"]: r["title"] for r in read_csv("titles_en.csv")}
    strings = {r["he"].replace("‏", "").strip(): r["en"] for r in read_csv("strings_en.csv")}

    def en(v):
        if v is None:
            return None
        v = str(v).replace("‏", "").strip()
        if not re.search("[֐-׿]", v):
            return v
        if v not in strings:
            raise SystemExit(f"No English for: {v!r} (add it to strings_en.csv)")
        return strings[v]

    wb = openpyxl.load_workbook(SRC / "grid-reinforcement-works.xlsx", read_only=True)
    sheets = wb.worksheets
    plan = {}
    for r in sheets[1].iter_rows(min_row=2, values_only=True):
        if r[0]:
            plan[r[0]] = {"match": en(r[4]), "official": en(r[5]), "pd_ret": r[6], "pai": r[7], "gap": r[8],
                          "finding": en(r[9]), "note": en(r[10])}

    names = set()
    for kind, items in S.values():
        for x in items:
            names.update(x if isinstance(x, list) else [x])
    st = resolve_stations(names, osm, places)
    net = Network(osm)
    polys = load_counties()
    print(f"Network: {len(net.coord)} nodes, {net.bridged} gaps bridged")

    works, legs_total, legs_routed = [], 0, 0
    for r in sheets[0].iter_rows(min_row=2, values_only=True):
        wid = r[0]
        if not wid:
            continue
        kind, items = S[wid]
        kv = str(r[4]) if r[4] else ""
        classes = {f"{kv}000"} if kv in ("110", "220", "400") else None
        lines, points, missing = [], [], []
        m = re.search(r"\(([\d.,]+) km", titles[wid])
        stated = float(m.group(1).replace(",", ".")) * 1000 if m else None
        single = kind == "L" and len(items) == 1 and sum(1 for n in items[0] if st.get(n)) == 2
        chain_names = {n for c in items for n in c} if kind != "P" else set()
        if kind == "P":
            for n in items:
                (points if st.get(n) else missing).append(n)
        else:
            for chain in items:
                found = [n for n in chain if st.get(n)]
                missing += [n for n in chain if not st.get(n)]
                for a, b in zip(found, found[1:]):
                    A, B = st[a], st[b]
                    straight = dist_m((A["lat"], A["lon"]), (B["lat"], B["lon"]))
                    leg = {"from": a, "to": b, "routed": False}
                    if kind == "L":
                        legs_total += 1
                        for cls in ([classes] if classes else []) + [None]:
                            path = net.route(A, B, cls)
                            if not path:
                                continue
                            km = polyline_m(path)
                            # Between two OSM substations a length the source states settles it;
                            # otherwise the route may not wander far from straight.
                            if stated and single and A["precision"] == B["precision"] == "osm":
                                fair = 0.75 * stated <= km <= 1.3 * stated
                            else:
                                fair = max(0.6 * straight - 2000, 0.3 * straight) <= km <= MAX_DETOUR * straight + 3000
                            if fair and not net.passes_through(path, A, B, chain_names):
                                leg.update(routed=True, kv="/".join(sorted({k[:-3] for k in (cls or ())})) or "any")
                                # A town-placed end moves to the line end the route reached.
                                for end, p in ((A, path[0]), (B, path[-1])):
                                    if end["precision"] == "town":
                                        end.setdefault("snaps", []).append(p)
                                break
                        if leg["routed"]:
                            legs_routed += 1
                            leg["c"] = [[round(p[0], 5), round(p[1], 5)] for p in simplify(path)]
                    if not leg["routed"]:
                        leg["c"] = [[A["lat"], A["lon"]], [B["lat"], B["lon"]]]
                    leg["km"] = round(polyline_m(leg["c"]) / 1000, 1)
                    lines.append(leg)
                for n in found:
                    if n not in points:
                        points.append(n)
        works.append({
            "id": wid, "title": titles[wid], "stated_km": round(stated / 1000, 3) if stated and lines else None, "type": en(r[3]), "kv": kv, "year": None if r[5] == "בלי מועד" else int(r[5]),
            "status": en(r[6]), "owner": r[7], "criterion": en(r[8]), "wording": en(r[9]), "conflicts": en(r[10]),
            "kind": kind, "lines": lines, "points": points, "missing": sorted(set(missing)),
            "note": en(NOTES.get(wid)), "plan": plan.get(wid),
        })

    # A town-placed station sits at the line end its routes reached (the first, if they differ).
    for s in st.values():
        if s and s.get("snaps"):
            s["lat"], s["lon"] = s["snaps"][0]
            s["precision"] = "line end"
    for w in works:
        for leg in w["lines"]:
            if not leg["routed"]:
                A, B = st[leg["from"]], st[leg["to"]]
                leg["c"] = [[A["lat"], A["lon"]], [B["lat"], B["lon"]]]
                leg["km"] = round(dist_m(*leg["c"]) / 1000, 1)
        pts = [st[n] for n in w["points"]]
        samples = [(p["lat"], p["lon"]) for p in pts] + [tuple(c) for leg in w["lines"] for c in leg["c"][::3]]
        w["counties"] = sorted({c for c in (county_of(la, lo, polys) for la, lo in samples) if c})
        w["km"] = round(sum(leg["km"] for leg in w["lines"]), 1) if w["lines"] else None

    used = {n for w in works for n in w["points"]}
    stations = {}
    for n in sorted(used):
        s = st[n]
        stations[n] = {k: s[k] for k in ("lat", "lon", "precision", "osm", "osm_name", "kv", "place", "note") if s.get(k) not in (None, "")}
        stations[n]["lat"], stations[n]["lon"] = round(s["lat"], 5), round(s["lon"], 5)
        stations[n]["county"] = county_of(s["lat"], s["lon"], polys)

    OUT.write_text(json.dumps({
        "generated": date.today().isoformat(), "osm_fetched": osm["fetched"],
        "works": works, "stations": stations,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    unplaced = sorted(n for n, s in st.items() if not s)
    print(f"{len(works)} works, {len(stations)} stations ({sum(1 for s in stations.values() if s['precision'] == 'osm')} from OSM)")
    print(f"Existing-line legs routed along OSM lines: {legs_routed} of {legs_total}")
    print(f"Stations not placed: {', '.join(unplaced) or 'none'}")
    print(f"Wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
