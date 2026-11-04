"""Build data/datacenters.json: Romania's data centres, one record per site, with sources.

Inputs (data/source/datacenters/):
  sites.csv            the curated list, one row per site (edited by hand). kind:
                         facility  a data centre building (its street address may still be unknown)
                         tenant    a company's space inside another listed building (hosted_in names it) or at a
                                   shared address
                         listing   a company listed in a directory as having a data centre, building unknown
                         project   under construction, permitted, announced or proposed; its MW and areas are planned
                       Areas: whitespace_m2 (space for IT racks), building_m2 (built area), plot_m2 (land).
                       atlas_type: how the Datacenter Atlas classifies the site (data centre / network point of presence).
  source_matches.csv   every row of every directory, and the site it was matched to: the audit trail that shows
                       nothing was dropped or counted twice.
  peeringdb/*.json     PeeringDB snapshot (facilities, networks, exchanges, carriers), refreshed by --refresh-peeringdb.
  geocode_cache.json   OpenStreetMap Nominatim results for sites without PeeringDB coordinates.

Reliability grade, counting only independent confirmations. The Datacenter Atlas copies most records from PeeringDB
(and the rest from OpenStreetMap), so it counts only for a site PeeringDB does not list. DC Hub copies PeeringDB and other
directories (its unverified rows repeat datacenters.com names), so it never counts as a confirmation.
  A  the operator itself (PeeringDB entry or its own website) plus at least one independent source
  B  the operator alone, or two independent sources
  C  a single source

Run from the project root:  python3 scripts/build_datacenters.py [--refresh-peeringdb]
"""
import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "source" / "datacenters"
PDB = SRC / "peeringdb"
OUT = ROOT / "data" / "datacenters.json"
UA = "RomaniaPowerMap/1.0 (https://github.com/matand299/romania-power-map)"

SOURCE_INFO = {
    "pdb": ("PeeringDB", "Entered by the operator", "primary"),
    "operator": ("Operator", "The operator's own website or announcement", "primary"),
    "gts": ("GTS Telecom", "The operator's own website", "primary"),
    "dccom": ("datacenters.com", "Directory", "independent"),
    "inflect": ("Inflect", "Directory", "independent"),
    "baxtel": ("Baxtel", "Directory", "independent"),
    "news": ("News", "Press reports", "independent"),
    "atlas": ("Datacenter Atlas", "Directory, mostly built from PeeringDB and OpenStreetMap", "derived"),
    "dchub": ("DC Hub", "Directory, built from PeeringDB and other directories", "derived"),
}
SOURCE_URL = {"atlas": "https://www.datacenter-atlas.com/country/romania", "dchub": "https://dchub.cloud/facilities/in/ro",
              "inflect": "https://inflect.com/datacenters/romania", "baxtel": "https://baxtel.com/data-center/romania",
              "gts": "https://www.gts.ro/en/data-center-romania"}
STATUS = {"operating": "Operating", "construction": "Under construction", "permitted": "Permitted", "announced": "Announced",
          "proposal": "Proposal", "unverified": "Unverified"}


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.load(r)


def refresh_peeringdb():
    """Download a fresh PeeringDB snapshot for Romania."""
    fac = get_json("https://www.peeringdb.com/api/fac?country=RO&depth=2")
    ids = ",".join(str(f["id"]) for f in fac["data"])
    files = {"fac": fac}
    for name in ("netfac", "ixfac", "carrierfac"):
        time.sleep(3)
        files[name] = get_json(f"https://www.peeringdb.com/api/{name}?fac_id__in={ids}")
    for name, key, fields in (("net", "net_id", "id,name,asn,info_type"), ("ix", "ix_id", "id,name,name_long,city"),
                              ("carrier", "carrier_id", "id,name")):
        want = ",".join(sorted({str(r[key]) for r in files[f"{name}fac"]["data"]}))
        time.sleep(3)
        files[name] = get_json(f"https://www.peeringdb.com/api/{name}?id__in={want}&fields={fields}")
    for name, data in files.items():
        (PDB / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"PeeringDB refreshed: {len(fac['data'])} facilities")


class Geocoder:
    """OpenStreetMap Nominatim, at most one request a second, with every answer cached in the repo."""

    def __init__(self):
        self.path = SRC / "geocode_cache.json"
        self.cache = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.last = 0.0

    def _get(self, url):
        if url not in self.cache:
            time.sleep(max(0.0, 1.1 - (time.time() - self.last)))
            self.cache[url] = get_json(url)
            self.last = time.time()
        return self.cache[url]

    def search(self, query):
        hits = self._get("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
            {"q": query, "countrycodes": "ro", "format": "jsonv2", "addressdetails": 1, "limit": 1}))
        return hits[0] if hits else None

    def county(self, lat, lon):
        r = self._get("https://nominatim.openstreetmap.org/reverse?" + urllib.parse.urlencode(
            {"lat": f"{lat:.5f}", "lon": f"{lon:.5f}", "format": "jsonv2", "zoom": 10, "addressdetails": 1}))
        a = r.get("address", {})
        c = a.get("county") or a.get("state") or a.get("city") or ""
        c = c.replace("Județul ", "").replace("Municipiul ", "")
        return "București" if c in ("București", "Bucharest") else c

    def save(self):
        self.path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")


ROADS = ("road", "street", "primary", "secondary", "tertiary", "trunk", "residential", "highway", "unclassified", "living_street")
AREAS = ("suburb", "neighbourhood", "quarter", "city_district", "borough")
ABBREV = {"Str. ": "Strada ", "Bd. ": "Bulevardul ", "Șos. ": "Șoseaua ", "Intr. ": "Intrarea "}


def expand(address):
    """Nominatim does not know Romanian street abbreviations."""
    for short, full in ABBREV.items():
        address = address.replace(short, full)
    return address


def num(v):
    return float(v) if v not in ("", None) else None


def grade(keys):
    primary = any(SOURCE_INFO[k][2] == "primary" for k in keys)
    independent = sum(1 for k in keys if SOURCE_INFO[k][2] == "independent")
    independent += 1 if ("atlas" in keys and "pdb" not in keys) else 0  # then the Atlas record comes from OpenStreetMap
    if primary and independent >= 1:
        return "A"
    if primary or independent >= 2:
        return "B"
    return "C"


def main():
    if "--refresh-peeringdb" in sys.argv:
        refresh_peeringdb()
    load = lambda n: json.loads((PDB / f"{n}.json").read_text(encoding="utf-8"))["data"]
    fac = {f["id"]: f for f in load("fac")}
    nets = {n["id"]: n for n in load("net")}
    ixs = {x["id"]: x for x in load("ix")}
    carriers = {c["id"]: c for c in load("carrier")}
    by_fac = lambda rows, key, table: {fid: sorted({table[r[key]]["name"] for r in rows if r["fac_id"] == fid and r[key] in table})
                                       for fid in fac}
    fac_nets = {fid: sorted(({"name": nets[r["net_id"]]["name"], "asn": nets[r["net_id"]]["asn"]} for r in load("netfac")
                             if r["fac_id"] == fid and r["net_id"] in nets), key=lambda n: n["name"].lower()) for fid in fac}
    fac_ix = by_fac(load("ixfac"), "ix_id", ixs)
    fac_carriers = by_fac(load("carrierfac"), "carrier_id", carriers)

    sites = list(csv.DictReader(open(SRC / "sites.csv", encoding="utf-8")))
    matches = list(csv.DictReader(open(SRC / "source_matches.csv", encoding="utf-8")))
    ids = {s["id"] for s in sites}
    assert len(ids) == len(sites), "duplicate site id in sites.csv"
    pdb_ids = [int(s["pdb_id"]) for s in sites if s["pdb_id"]]
    assert sorted(pdb_ids) == sorted(fac), f"PeeringDB facilities not in sites.csv: {sorted(set(fac) - set(pdb_ids))}"
    dccom_url = {}
    for m in matches:
        assert m["site_id"] == "" or m["site_id"] in ids, m
        if m["source"] == "datacenters.com" and m["site_id"]:
            dccom_url.setdefault(m["site_id"], m["source_url"])

    geo = Geocoder()
    out = {}
    for s in sites:
        keys = s["sources"].split()
        rec = {k: s[k] for k in ("id", "kind", "name", "operator", "aka", "address", "city", "county", "tier", "opened", "website", "notes", "hosted_in")}
        rec["status"] = STATUS[s["status"]]
        rec["atlas_type"] = s["atlas_type"]
        for k in ("it_mw", "total_mw", "grid_mw", "planned_mw", "whitespace_m2", "building_m2", "plot_m2", "racks"):
            rec[k] = num(s[k])
        lat, lon, precision = num(s["lat"]), num(s["lon"]), "given" if s["lat"] else ""
        if s["pdb_id"]:
            f = fac[int(s["pdb_id"])]
            rec["address"] = rec["address"] or ", ".join(x for x in (f["address1"], f["address2"]) if x)
            rec["city"] = rec["city"] or f["city"]
            rec["website"] = rec["website"] or f["website"]
            if f["latitude"] is not None and lat is None:
                lat, lon, precision = f["latitude"], f["longitude"], "building (PeeringDB)"
            # (PeeringDB's "updated" date is not shown: a bulk update stamped nearly every record on the same day.)
            rec["peeringdb"] = {"id": f["id"], "url": f"https://www.peeringdb.com/fac/{f['id']}", "created": f["created"][:10]}
            rec["networks"] = fac_nets[f["id"]]
            rec["exchanges"] = fac_ix[f["id"]]
            rec["carriers"] = fac_carriers[f["id"]]
        if lat is None and not s["hosted_in"]:
            hit = None
            if rec["address"] and any(ch.isdigit() for ch in rec["address"]):
                hit = geo.search(f"{expand(rec['address'])}, {rec['city']}, Romania")
                number = rec["address"].split()[-1]
                if hit and (hit.get("addresstype") in ("house", "building", "amenity", "office", "commercial", "industrial")
                            or hit["display_name"].startswith(number + ",")):
                    precision = "address"
                elif hit and hit.get("addresstype") in ROADS:
                    precision = "street"
                else:
                    hit = None
            if hit is None and rec["address"]:
                street = expand(rec["address"]).split(" (")[0].rstrip("0123456789-– ").rstrip(",")
                hit = geo.search(f"{street}, {rec['city']}, Romania")
                if hit and hit.get("addresstype") in AREAS:
                    precision = "district"
                elif hit and hit.get("addresstype") in ROADS:
                    precision = "street"
                else:
                    hit = None  # a building somewhere on the street would look more precise than it is
            if hit is None:
                town = rec["city"].split(" (")[0]
                hit = geo.search(f"{town}, {s['county'] + ', ' if s['county'] else ''}Romania")
                precision = "town" if hit else ""
            if hit:
                lat, lon = float(hit["lat"]), float(hit["lon"])
        rec["lat"], rec["lon"], rec["precision"] = lat, lon, precision
        rec["source_keys"] = keys
        rec["sources"] = []
        for k in keys:
            name, kind, _ = SOURCE_INFO[k]
            url = (rec.get("peeringdb", {}).get("url") if k == "pdb" else dccom_url.get(s["id"]) if k == "dccom" else SOURCE_URL.get(k, ""))
            rec["sources"].append({"name": name, "kind": kind, "url": url or ""})
        rec["links"] = [u for u in s["links"].split("|") if u]
        rec["listed_as"] = sorted({f"{m['source']}: {m['source_name']}" for m in matches if m["site_id"] == s["id"] and m["match"] in ("match", "possible")})
        rec["grade"] = grade(keys)
        out[s["id"]] = rec

    # Presences take their host's location; then every located site gets its county from its coordinates.
    for rec in out.values():
        if rec["hosted_in"]:
            host = out[rec["hosted_in"]]
            rec["lat"], rec["lon"], rec["precision"] = host["lat"], host["lon"], f"host building ({host['name']})"
        if rec["lat"] is not None:
            rec["county"] = rec["county"] or geo.county(rec["lat"], rec["lon"])
    geo.save()

    result = {
        "generated": date.today().isoformat(),
        "about": "Romania's data centres, one record per site. See scripts/build_datacenters.py for the method and grades.",
        "sources": {k: {"name": v[0], "kind": v[1]} for k, v in SOURCE_INFO.items()},
        "sites": list(out.values()),
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter
    print(f"datacenters.json: {len(out)} sites; kinds {dict(Counter(r['kind'] for r in out.values()))}; "
          f"grades {dict(Counter(r['grade'] for r in out.values()))}; "
          f"located {sum(1 for r in out.values() if r['lat'] is not None)}; "
          f"precision {dict(Counter(r['precision'].split(' (')[0] for r in out.values()))}")


if __name__ == "__main__":
    main()
