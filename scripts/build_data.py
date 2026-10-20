"""Build the map's data files from the ANRE Excel export.

Reads data/source/*.xlsx, cleans it, geocodes each plant to its locality
(GeoNames gazetteer) and writes:
  data/plants.json     - one record per licensed plant
  data/counties.json   - simplified county boundaries

Run from the project root:  python3 scripts/build_data.py
"""
import json
import re
import unicodedata
import urllib.request
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "source"
EXCEL = SRC / "Puteri-capacitati_24.04.2023_Final_EN_With_Status.xlsx"
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


def build_counties():
    src = json.loads(COUNTIES_IN.read_text(encoding="utf-8"))
    feats = []
    for f in src["features"]:
        geom = f["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        polys = [[simplify_ring(r) for r in p] for p in polys]
        feats.append({"type": "Feature", "properties": {"name": f["properties"]["name"]},
                      "geometry": {"type": "MultiPolygon", "coordinates": polys}})
    out = ROOT / "data" / "counties.json"
    out.write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                              separators=(",", ":")), encoding="utf-8")
    print(f"counties.json: {out.stat().st_size // 1024} KB")


def status_of(value):
    """The register marks each licence as operating or expired (text may be bilingual)."""
    return "Expired" if "expired" in str(value).lower() else "Operating"


def main():
    ensure_geonames()
    gaz = load_gazetteer()
    df = pd.read_excel(EXCEL)
    df = df[df["Plant Name"].notna() & df["Primary Energy / Technology"].notna()]
    col = {c: i for i, c in enumerate(df.columns)}

    plants, exact = [], 0
    for r in df.itertuples(index=False):
        county = str(r[col["County (Judet)"]]).strip()
        # The gazetteer match is preferred: the spreadsheet's coordinates are mostly county centres.
        hit = geocode(gaz, county, r[col["Locality / City"]], r[col["Plant Name"]])
        if hit:
            lat, lon, precise = hit[0], hit[1], True
            exact += 1
        else:
            lat, lon, precise = float(r[col["Latitude"]]), float(r[col["Longitude"]]), False
        tech = str(r[col["Primary Energy / Technology"]]).strip()

        def d(v):
            return v.strftime("%Y-%m-%d") if pd.notna(v) else None

        plants.append({
            "n": str(r[col["Plant Name"]]).strip(),
            "co": str(r[col["Company / Economic Operator"]]).strip(),
            "loc": str(r[col["Locality / City"]]).strip(),
            "cty": county,
            "mw": round(float(r[col["Installed Capacity (MW)"]]), 4) if pd.notna(r[col["Installed Capacity (MW)"]]) else 0,
            "t": TECH_NAMES.get(tech, tech),
            "st": status_of(r[col["Status / Stage"]]),
            "lic": int(r[col["License Number"]]) if pd.notna(r[col["License Number"]]) else None,
            "iss": d(r[col["Issue Date"]]),
            "exp": d(r[col["Expiration Date"]]),
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "p": precise,
        })

    out = ROOT / "data" / "plants.json"
    out.write_text(json.dumps({"source": "ANRE - licensed power generation capacities, 24.04.2023",
                               "plants": plants}, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    print(f"plants.json: {len(plants)} plants, {exact} geocoded to locality, "
          f"{len(plants) - exact} left at the spreadsheet's coordinates")
    print("status:", pd.Series([p["st"] for p in plants]).value_counts().to_dict())
    print("technologies:", pd.Series([p["t"] for p in plants]).value_counts().to_dict())
    build_counties()


if __name__ == "__main__":
    main()
