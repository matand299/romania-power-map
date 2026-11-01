"""Download Transelectrica's current installed capacity files into data/source/transelectrica/.

Transelectrica (DEN) publishes them monthly on https://www.transelectrica.ro/ro/web/tel/productie:
  7productie23.xls   - sheet "Stocare": every storage installation in the grid
  7productie12a.xls  - sheet "Fotovoltaice": installed capacity per relevant solar plant
The links are read from that page, so a new upload is picked up. A file replaces the one in the
repository only if it opens and still has the sheet the build reads, so a broken download cannot
empty the map's layers.

Run from the project root:  python3 scripts/fetch_transelectrica.py
"""
import re
import tempfile
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "data" / "source" / "transelectrica"
SITE = "https://www.transelectrica.ro"
PAGE = SITE + "/ro/web/tel/productie"
FILES = {"7productie23.xls": "Stocare", "7productie12a.xls": "Fotovoltaice"}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (romania-power-map data update)"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read()


def main():
    page = get(PAGE).decode("utf-8", "ignore")
    DEST.mkdir(parents=True, exist_ok=True)
    for name, sheet in FILES.items():
        link = re.search(rf'/documents/[^"\s]*/{re.escape(name)}/[0-9a-f-]+', page)
        if not link:
            raise SystemExit(f"{name}: no link on {PAGE}")
        data = get(SITE + link.group(0))
        with tempfile.NamedTemporaryFile(suffix=".xls") as tmp:
            tmp.write(data)
            tmp.flush()
            df = pd.read_excel(tmp.name, sheet_name=sheet, header=None)
        as_of = re.search(r"\d{2}\.\d{2}\.\d{4}", " ".join(map(str, df.iloc[:6, 0])))
        rows = pd.to_numeric(df[0], errors="coerce").notna().sum()
        if not as_of or rows == 0:
            raise SystemExit(f"{name}: sheet {sheet} has no date or no rows; keeping the current file")
        (DEST / name).write_bytes(data)
        print(f"{name}: {sheet}, {rows} rows, data of {as_of.group(0)}")


if __name__ == "__main__":
    main()
