"""Fetch ANRE's official installed capacity totals by primary energy type.

ANRE publishes them on https://anre.ro/puteri-instalate as a public Power BI report. This script
asks the report's data service the same question the report's own table asks (no browser needed)
and writes data/anre_totals.json, which the map compares with what it shows.

Run from the project root:  python3 scripts/fetch_anre_totals.py
"""
import gzip
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "anre_totals.json"

# Identifiers of ANRE's public "Puteri instalate" report.
API = "https://wabi-west-europe-d-primary-api.analysis.windows.net/public/reports"
RESOURCE_KEY = "26133983-3d01-4513-8973-6f75b7d00733"
MODEL_ID = 4228344
DATASET_ID = "c77d73e5-705b-416e-83ce-cb2aa7df310a"
REPORT_ID = "c902cac2-9bdd-46c0-9a1d-225ece6e5890"
PAGE_URL = "https://anre.ro/puteri-instalate"


def fetch(url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None, headers={
        "Content-Type": "application/json;charset=UTF-8", "X-PowerBI-ResourceKey": RESOURCE_KEY})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    return json.loads(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)


def column(prop):
    return {"Column": {"Expression": {"SourceRef": {"Source": "c"}}, "Property": prop}}


def query(select):
    """Run one semantic query against the report's single table; return the data-shape rows."""
    q = {"Version": 2, "From": [{"Name": "c", "Entity": "ct_total_puteri", "Type": 0}], "Select": select}
    body = {
        "version": "1.0.0",
        "queries": [{
            "Query": {"Commands": [{"SemanticQueryDataShapeCommand": {
                "Query": q,
                "Binding": {"Primary": {"Groupings": [{"Projections": list(range(len(select)))}]},
                            "DataReduction": {"DataVolume": 3, "Primary": {"Window": {"Count": 500}}},
                            "Version": 1},
            }}]},
            "ApplicationContext": {"DatasetId": DATASET_ID, "Sources": [{"ReportId": REPORT_ID}]},
        }],
        "cancelQueries": [],
        "modelId": MODEL_ID,
    }
    data = fetch(f"{API}/querydata?synchronous=true", body)["results"][0]["result"]["data"]
    rows, prev, names = [], [], []
    for group in data["dsr"]["DS"][0]["PH"]:
        for row in group.get("DM0", []) + group.get("DM1", []):
            names = [s["N"] for s in row.get("S", [])] or names
            # Rows hold their values in "C"; a single-value answer names it instead (e.g. "M0").
            cells = row["C"] if "C" in row else [row[n] for n in names if n in row]
            # Power BI compresses repeated values: "R" marks cells copied from the previous row.
            repeat = row.get("R", 0)
            full, it = [], iter(cells)
            for i in range(len(select)):
                full.append(prev[i] if repeat >> i & 1 else next(it, None))
            rows.append(full)
            prev = full
    return rows


def main():
    rows = query([
        {**column("TipEnergiePrimara"), "Name": "type"},
        {"Aggregation": {"Expression": column("Total_PE"), "Function": 0}, "Name": "mw"},
    ])
    totals = {t: round(float(mw), 3) for t, mw in rows if t is not None and mw is not None}
    # The report's own date shows today's date; the figures date from the dataset's last refresh.
    model = fetch(f"{API}/{RESOURCE_KEY}/modelsAndExploration?preferReadOnlySession=true")["models"][0]
    as_of = model["LastRefreshTime"][:10]
    if not totals:
        raise SystemExit("ANRE report returned no totals")
    OUT.write_text(json.dumps({
        "source": "ANRE, Puteri instalate (installed capacity by primary energy type)",
        "url": PAGE_URL,
        "as_of": as_of,
        "mw": dict(sorted(totals.items(), key=lambda kv: -kv[1])),
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"anre_totals.json: {len(totals)} types, {sum(totals.values()):,.0f} MW, as of {as_of}")


if __name__ == "__main__":
    main()
