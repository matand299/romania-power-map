"""Build the map's data files from the Romania energy projects master database.

Reads the master Excel (operating plants and the development pipeline from ANRE,
Transelectrica, the distribution operators and Global Energy Monitor), removes
subtotal rows and cross-source duplicates, fixes kW/MW slips, normalises
technologies, stages and counties, and writes:
  data/plants.json     - one record per project
  data/counties.json   - simplified county boundaries with label points

Run from the project root:  python3 scripts/build_data.py
"""
import json
import math
import re
import unicodedata
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "source"
EXCEL = SRC / "Romania_Energy_Projects_Master_Database_2026_EN.xlsx"
# Earlier ANRE export, used only for licence issue and expiry dates.
ANRE_LICENCES = SRC / "Puteri-capacitati_24.04.2023_Final_EN_With_Status.xlsx"
GEONAMES = SRC / "geonames_RO.txt"
ADMIN1 = SRC / "geonames_admin1_RO.txt"
COUNTIES_IN = SRC / "ro_counties.geojson"

TECH_NAMES = {
    "Natural Gas / Hydrocarbons": "Natural Gas",
    "Hidrocarburi": "Natural Gas",
    "Hidro": "Hydro",
    "Eolian": "Wind",
    "Biogaz": "Biogas",
    "Biomasa": "Biomass",
    "Carbune": "Coal",
    "Deseuri": "Waste",
    "Caldura reziduala": "Waste Heat",
    "Geotermal": "Geothermal",
}

# County codes used in brackets inside locality names, e.g. "Sancraiu [CJ]".
COUNTY_CODES = {
    "AB": "Alba", "AR": "Arad", "AG": "Arges", "BC": "Bacau", "BH": "Bihor",
    "BN": "Bistrita-Nasaud", "BT": "Botosani", "BR": "Braila", "BV": "Brasov",
    "B": "Bucuresti", "BZ": "Buzau", "CL": "Calarasi", "CS": "Caras Severin",
    "CJ": "Cluj", "CT": "Constanta", "CV": "Covasna", "DB": "Dambovita",
    "DJ": "Dolj", "GL": "Galati", "GR": "Giurgiu", "GJ": "Gorj", "HR": "Harghita",
    "HD": "Hunedoara", "IL": "Ialomita", "IS": "Iasi", "IF": "Ilfov",
    "MM": "Maramures", "MH": "Mehedinti", "MS": "Mures", "NT": "Neamt", "OT": "Olt",
    "PH": "Prahova", "SJ": "Salaj", "SM": "Satu Mare", "SB": "Sibiu", "SV": "Suceava",
    "TR": "Teleorman", "TM": "Timis", "TL": "Tulcea", "VL": "Valcea", "VS": "Vaslui",
    "VN": "Vrancea",
}

# Romanian plant-name prefixes (CEF = solar park, MHC = small hydro, ...).
NAME_PREFIXES = {"cef", "cee", "mhc", "che", "chee", "cet", "cte", "cne", "ce", "cf",
                 "ceb", "cco", "ccc", "sh", "uhe", "amenajarea", "parc", "fotovoltaic",
                 "eolian", "biogaz", "biomasa", "centrala", "electrica", "hidro"}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    s = re.sub(r"\[.*?\]|\(.*?\)", " ", s.lower())
    s = re.sub(r"\bcounty\b|\bjudetul\b|\bmunicipiul\b|\boras(ul)?\b|\bcomuna\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def ensure_geonames():
    if GEONAMES.exists():
        return
    print("Downloading GeoNames gazetteer for Romania...")
    zpath = SRC / "RO.zip"
    urllib.request.urlretrieve("https://download.geonames.org/export/dump/RO.zip", zpath)
    with zipfile.ZipFile(zpath) as z:
        GEONAMES.write_bytes(z.read("RO.txt"))
    zpath.unlink()


def load_gazetteer():
    """Return {county_norm: {place_norm: (lat, lon, rank)}} for populated places."""
    admin = {}
    for line in ADMIN1.read_text(encoding="utf-8").splitlines():
        code, _, ascii_name, _ = line.split("\t")
        name = norm(ascii_name)
        admin[code.split(".")[1]] = "bucuresti" if name == "bucharest" else name

    cols = ["id", "name", "ascii", "alt", "lat", "lon", "fclass", "fcode", "cc", "cc2",
            "a1", "a2", "a3", "a4", "pop", "elev", "dem", "tz", "mod"]
    g = pd.read_csv(GEONAMES, sep="\t", names=cols, usecols=range(19), dtype=str,
                    keep_default_na=False, quoting=3)
    g = g[g.fclass == "P"]
    order = {"PPLC": 0, "PPLA": 1, "PPLA2": 2, "PPLA3": 3, "PPL": 4}
    gaz = {}
    for r in g.itertuples():
        county = admin.get(r.a1)
        if not county:
            continue
        rank = (order.get(r.fcode, 5), -int(r.pop or 0))
        names = {r.name, r.ascii} | {a for a in r.alt.split(",") if a and len(a) < 40}
        bucket = gaz.setdefault(county, {})
        for n in names:
            key = norm(n)
            if key and (key not in bucket or rank < bucket[key][2]):
                bucket[key] = (float(r.lat), float(r.lon), rank)
    return gaz


def locality_candidates(locality, plant):
    """Yield (county_override, name) guesses, most specific first."""
    loc = str(locality or "")
    m = re.search(r"\[([A-Z]{1,2})\]", loc)
    override = COUNTY_CODES.get(m.group(1)) if m else None
    yield override, loc
    # Plant names usually carry the locality: "CEF Popesti Voivozi 3 [BH]".
    words = [w for w in norm(plant).split() if w not in NAME_PREFIXES and not w.isdigit()]
    for n in (3, 2, 1):
        for i in range(len(words) - n + 1):
            yield override, " ".join(words[i:i + n])


def geocode(gaz, county, locality, plant):
    for override, name in locality_candidates(locality, plant):
        bucket = gaz.get(norm(override or county), {})
        hit = bucket.get(norm(name))
        if hit:
            return hit[0], hit[1]
    return None


def simplify_ring(ring, step=0.004):
    out, last = [], None
    for x, y in ring:
        p = (round(x, 3), round(y, 3))
        if last is None or abs(p[0] - last[0]) + abs(p[1] - last[1]) >= step:
            out.append(p)
            last = p
    if out[0] != out[-1]:
        out.append(out[0])
    return out


# Map labels use the Romanian spelling; the boundary file has plain ASCII names.
COUNTY_LABELS = {
    "Arges": "Argeș", "Bacau": "Bacău", "Bistrita-Nasaud": "Bistrița-Năsăud", "Botosani": "Botoșani",
    "Braila": "Brăila", "Brasov": "Brașov", "Bucuresti": "București", "Bucharest": "București", "Buzau": "Buzău",
    "Calarasi": "Călărași", "Caras-Severin": "Caraș-Severin", "Constanta": "Constanța", "Dambovita": "Dâmbovița",
    "Galati": "Galați", "Ialomita": "Ialomița", "Iasi": "Iași", "Maramures": "Maramureș", "Mehedinti": "Mehedinți",
    "Mures": "Mureș", "Neamt": "Neamț", "Salaj": "Sălaj", "Timis": "Timiș", "Valcea": "Vâlcea",
}


def point_in_ring(x, y, ring):
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def dist_to_ring(x, y, ring, kx):
    best = float("inf")
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        dx, dy = (x2 - x1) * kx, y2 - y1
        px, py = (x - x1) * kx, y - y1
        t = max(0.0, min(1.0, (px * dx + py * dy) / (dx * dx + dy * dy or 1)))
        best = min(best, (px - t * dx) ** 2 + (py - t * dy) ** 2)
    return best ** 0.5


def label_point(polys):
    """Point deepest inside the county's largest polygon, so the name sits well clear of borders."""
    def area(r):
        return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(r, r[1:]))) / 2
    poly = max(polys, key=lambda p: area(p[0]))
    outer, holes = poly[0], poly[1:]
    xs, ys = [x for x, _ in outer], [y for _, y in outer]
    kx = math.cos(math.radians(sum(ys) / len(ys)))
    best, best_d = (sum(xs) / len(xs), sum(ys) / len(ys)), -1
    n = 36
    for i in range(n + 1):
        for j in range(n + 1):
            x = min(xs) + (max(xs) - min(xs)) * i / n
            y = min(ys) + (max(ys) - min(ys)) * j / n
            if not point_in_ring(x, y, outer) or any(point_in_ring(x, y, h) for h in holes):
                continue
            d = min(dist_to_ring(x, y, r, kx) for r in poly)
            if d > best_d:
                best, best_d = (x, y), d
    return [round(best[1], 4), round(best[0], 4)]


def build_counties():
    src = json.loads(COUNTIES_IN.read_text(encoding="utf-8"))
    feats = []
    for f in src["features"]:
        geom = f["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        polys = [[simplify_ring(r) for r in p] for p in polys]
        name = f["properties"]["name"]
        feats.append({"type": "Feature",
                      "properties": {"name": name, "label": COUNTY_LABELS.get(name, name), "lp": label_point(polys)},
                      "geometry": {"type": "MultiPolygon", "coordinates": polys}})
    out = ROOT / "data" / "counties.json"
    out.write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                              separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print(f"counties.json: {out.stat().st_size // 1024} KB")


TECH_MAP = {
    "Solar": "Solar", "Wind": "Wind", "Hydro": "Hydro", "Natural Gas": "Natural Gas", "Coal": "Coal",
    "Nuclear": "Nuclear", "Biomass": "Biomass", "Biogas": "Biogas", "BESS / Storage": "Storage",
    "CES": "Storage", "Hybrid / Mixed": "Hybrid", "CEM": "Hybrid", "CEG + IS": "Hybrid",
    "Thermal": "Thermal / Other", "Thermal / Other": "Thermal / Other", "תרמי / אחר": "Thermal / Other",
    "פסולת": "Waste", "חום שיורי": "Waste Heat", "Other": "Other",
}

# Stages in pipeline order; keys are the labels used in the master file.
STAGE_MAP = {
    "Operating": "Operating",
    "Operating (Licensed)": "Operating",
    "DEO — הופעל (PIF)": "Commissioned (PIF)",
    "חובר פיזית / PIF (רשת הולכה)": "Commissioned (PIF)",
    "Under Construction / Testing": "Under construction / testing",
    "Connection Certificate (CDC)": "Connection certificate (CDC)",
    "Planning / ATR / Pre-construction": "Planning / ATR / pre-construction",
    "מוקפא (Mothballed)": "Mothballed",
    "בוטל / סגור (Retired/Cancelled)": "Retired / cancelled",
}

SOURCE_PREFIXES = [
    ("ANRE", "ANRE licensed capacity register, 24.04.2023"),
    ("Transelectrica — Anexa 9.1", "Transelectrica, Annex 9.1: grid connection permits (ATR) and contracts"),
    ("Transelectrica — Anexa 9.2", "Transelectrica, Annex 9.2: connection certificates"),
    ("Transelectrica — Anexa 9.3", "Transelectrica, Annex 9.3: connection solution studies"),
    ("DEER (Electrica) — Anexa 9.1 אזור MN", "DEER (Electrica), Annex 9.1, Muntenia Nord, 30.11.2025"),
    ("DEER (Electrica) — Anexa 9.1 אזור TS", "DEER (Electrica), Annex 9.1, Transilvania Sud, 30.11.2025"),
    ("DEER (Electrica) — Anexa 9.1 אזור TN", "DEER (Electrica), Annex 9.1, Transilvania Nord, 30.11.2025"),
    ("Rețele Electrice România (PPC) — Anexa 9.1 אזור באנאט", "Rețele Electrice (PPC), Annex 9.1, Banat, Q2 2026"),
    ("Rețele Electrice România (PPC) — Anexa 9.1 אזור דוברוג'ה", "Rețele Electrice (PPC), Annex 9.1, Dobrogea, Q2 2026"),
    ("Rețele Electrice România (PPC) — Anexa 9.1 אזור מונטניה", "Rețele Electrice (PPC), Annex 9.1, Muntenia, Q2 2026"),
    ("DEO — Centralizator CE עם PIF", "Distribuție Energie Oltenia, plants commissioned (PIF), 02.10.2026"),
    ("DEO — Centralizator CEF", "Distribuție Energie Oltenia, solar parks in planning/approval, 02.10.2026"),
    ("DEO — רשימת תעודות חיבור", "Distribuție Energie Oltenia, connection certificates (CDC), 02.10.2026"),
]
ANRE_SOURCE = SOURCE_PREFIXES[0][1]
GEM_SOURCE = "Global Energy Monitor, Global Integrated Power Tracker (source column empty; identified by GEM unit IDs)"

COUNTY_FIX = {"lasi": "Iasi", "calarasi county": "Calarasi", "caras severin": "Caras-Severin"}
REGIONS = {"dobruja", "northern dobruja", "dobrogea", "dobrega", "oltenia", "olentia", "muntenia", "montenia", "banat",
           "moldavia", "western moldavia", "westerm moldavia", "crisana", "transylvania", "translyvania", "bokovina"}


def clean(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    return re.sub(r"\s+", " ", str(v)).strip()


def source_of(raw, status, ident):
    raw = clean(raw)
    for prefix, label in SOURCE_PREFIXES:
        if raw.startswith(prefix):
            return label
    if not raw and status == "Operating (Licensed)":
        return ANRE_SOURCE
    if not raw and ident.startswith("G1"):
        return GEM_SOURCE
    return raw or "Not stated"


MW_IN_TEXT = re.compile(r"(?:P[id]\s*=\s*)?(\d+(?:[.,]\d+)?)\s*(MW|kW)\b", re.I)


def fix_units(mw, text, source):
    """Distribution-operator rows sometimes carry kW in the MW column; recover MW from the description."""
    if not source.startswith("Distribuție Energie Oltenia") or mw <= 100:
        return mw, False
    for num, unit in MW_IN_TEXT.findall(text):
        val = float(num.replace(",", "."))
        val = val / 1000 if unit.lower() == "kw" else val
        if 0 < val <= 100:
            return val, True
    return mw / 1000, True


GENERIC_WORDS = {"wind", "farm", "solar", "park", "hydroelectric", "plant", "power", "station", "project", "photovoltaic",
                 "energy", "romania", "timepoint", "unit", "phase", "north", "south", "east", "west", "nord", "sud",
                 "est", "vest", "complex", "thermal", "combined", "cycle", "heat"}
# GEM uses English names for a few plants that ANRE lists in Romanian.
NAME_ALIASES = {"iron gate": "portile fier", "cernavoda": "cernavoda"}


def gem_name_words(name):
    text = norm(name.split(" – ")[0])
    for en, ro in NAME_ALIASES.items():
        text = text.replace(en, ro)
    return {w for w in text.split() if len(w) >= 5 and not w.isdigit() and w not in GENERIC_WORDS}


def haversine_km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def load_county_polygons():
    src = json.loads(COUNTIES_IN.read_text(encoding="utf-8"))
    out = []
    for f in src["features"]:
        g = f["geometry"]
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        out.append((f["properties"]["name"], polys))
    return out


def county_at(lat, lon, polygons):
    for name, polys in polygons:
        for poly in polys:
            if point_in_ring(lon, lat, poly[0]) and not any(point_in_ring(lon, lat, h) for h in poly[1:]):
                return name
    return None


def licence_dates():
    """Licence number -> (issued, expires) from the earlier ANRE export."""
    if not ANRE_LICENCES.exists():
        return {}
    df = pd.read_excel(ANRE_LICENCES)
    out = {}
    for r in df.itertuples(index=False):
        lic, iss, exp = r[2], r[3], r[4]
        if pd.notna(lic):
            out[int(lic)] = (iss.strftime("%Y-%m-%d") if pd.notna(iss) else None,
                             exp.strftime("%Y-%m-%d") if pd.notna(exp) else None)
    return out


# Placeholder points the master file uses when a project has no location (roughly the centre of Romania).
PLACEHOLDER_POINTS = [(45.9852, 24.6859), (45.9432, 24.9668)]


def national_index(gaz):
    """Place name -> best (lat, lon, county) anywhere in Romania, for rows with no usable county."""
    idx = {}
    for county, bucket in gaz.items():
        for key, (lat, lon, rank) in bucket.items():
            if key not in idx or rank < idx[key][3]:
                idx[key] = (lat, lon, county, rank)
    return idx


def place_by_name(idx, *texts):
    for text in texts:
        words = [w for w in norm(text).split() if w not in GENERIC_WORDS and not w.isdigit()]
        for n in (3, 2, 1):
            for i in range(len(words) - n + 1):
                hit = idx.get(" ".join(words[i:i + n]))
                if hit and len(" ".join(words[i:i + n])) >= 4:
                    return hit
    return None


def main():
    df = pd.read_excel(EXCEL, sheet_name="All Power Projects")
    ensure_geonames()
    national = national_index(load_gazetteer())
    polygons = load_county_polygons()
    county_names = {norm(n): ("Bucuresti" if n == "Bucharest" else n) for n, _ in polygons}
    dates = licence_dates()
    log = {"subtotal rows": 0, "notes / zero rows": 0, "kW fixed": 0, "ANRE duplicates": 0,
           "GEM operating already listed": 0, "county from coordinates": 0, "outside Romania": 0,
           "placeholder location re-placed": 0, "no usable location": 0}

    rows = []
    for r in df.to_dict("records"):
        plant, project = clean(r["Plant / Station Name"]), clean(r["Project / Investor Name"])
        ident, locality = clean(r["Original ID / License"]), clean(r["Locality / City"])
        status_raw = clean(r["Status / Stage"])
        mw = float(r["Installed Capacity (MW)"] or 0)
        if project.upper() == "TOTAL" or (not plant and not project and not locality and not ident):
            log["subtotal rows"] += 1
            continue
        if mw == 0 and not plant and not ident:
            log["notes / zero rows"] += 1
            continue
        source = source_of(r["Data Source"], status_raw, ident)
        mw, fixed = fix_units(mw, f"{plant} {project}", source)
        log["kW fixed"] += fixed

        lat, lon = float(r["Latitude"]), float(r["Longitude"])
        located = True
        if any(abs(lat - a) < 0.002 and abs(lon - b) < 0.002 for a, b in PLACEHOLDER_POINTS):
            hit = place_by_name(national, project, plant, locality)
            if hit:
                lat, lon = hit[0], hit[1]
                log["placeholder location re-placed"] += 1
            else:
                located = False
                log["no usable location"] += 1
        raw_cty = norm(clean(r["County (Judet)"]).split("/")[0].split("(")[0])
        raw_cty = norm(COUNTY_FIX.get(raw_cty, raw_cty))
        county = county_names.get(raw_cty)
        if not county and located:
            county = county_at(lat, lon, polygons)
            log["county from coordinates"] += bool(county)
        if located and not county_at(lat, lon, polygons):
            log["outside Romania"] += 1
        county = "Bucuresti" if county == "Bucharest" else county

        # GEM lists units ("CC, timepoint 1") under a project name; the project reads better first.
        if source == GEM_SOURCE and plant and plant != "--" and project and plant not in project:
            name = f"{project} – {plant}"
        else:
            name = plant if plant and plant != "--" else project
        desc = project if project and len(project) > 60 else ""
        if len(name) > 90:
            name = name[:87].rstrip(" ,;-") + "…"

        lic = re.search(r"(\d+)", ident) if source == ANRE_SOURCE else None
        lic = int(lic.group(1)) if lic else None
        iss, exp = dates.get(lic, (None, None)) if lic else (None, None)
        rows.append({
            "n": name or "Unnamed project",
            "co": clean(r["Owner / Operator"]) or (project if project != name and len(project) <= 60 else ""),
            "loc": locality, "cty": county or "", "mw": round(mw, 4),
            "t": TECH_MAP.get(clean(r["Technology"]), clean(r["Technology"]) or "Other"),
            "st": STAGE_MAP.get(status_raw, status_raw),
            "src": source, "id": ident, "lic": lic, "iss": iss, "exp": exp,
            "lat": round(lat, 5) if located else None, "lon": round(lon, 5) if located else None, "d": desc[:400],
        })

    # The ANRE register appears twice in the master file (with and without a source label).
    seen, deduped = set(), []
    for p in rows:
        key = (p["src"], norm(p["n"]), round(p["mw"], 2), p["lic"]) if p["src"] == ANRE_SOURCE else None
        if key and key in seen:
            log["ANRE duplicates"] += 1
            continue
        seen.add(key)
        deduped.append(p)

    # GEM "operating" units mostly repeat plants already listed as operating by ANRE or the grid operators.
    # Drop a GEM unit when such a plant of the same technology shares a distinctive name word, or lies
    # within 10 km and covers at least half of its capacity.
    anre = [p for p in deduped if p["src"] != GEM_SOURCE and p["st"] in ("Operating", "Commissioned (PIF)")]
    anre_words = [(a, set(norm(a["n"]).split())) for a in anre]
    plants = []
    for p in deduped:
        if p["src"] == GEM_SOURCE and p["st"] == "Operating":
            words = gem_name_words(p["n"])
            named = any(a["t"] == p["t"] and words & w for a, w in anre_words)
            near = sum(a["mw"] for a in anre if a["t"] == p["t"] and p["lat"] is not None
                       and haversine_km((a["lat"], a["lon"]), (p["lat"], p["lon"])) <= 10)
            if named or near >= 0.5 * p["mw"]:
                log["GEM operating already listed"] += 1
                continue
        plants.append(p)

    out = ROOT / "data" / "plants.json"
    out.write_text(json.dumps({"source": "Romania energy projects master database 2026", "plants": plants},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"plants.json: {len(plants)} projects ({out.stat().st_size // 1024} KB)")
    for k, v in log.items():
        print(f"  {k}: {v}")
    frame = pd.DataFrame(plants)
    print(frame.groupby("st")["mw"].agg(["size", "sum"]).round(0).to_string())
    print(frame.groupby("src")["mw"].agg(["size", "sum"]).round(0).to_string())
    print(frame["t"].value_counts().to_dict())
    print("no county:", (frame["cty"] == "").sum())
    build_counties()


if __name__ == "__main__":
    main()
