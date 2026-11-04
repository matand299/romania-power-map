"""Ground elevation under each plant, for standing the 3D models on the terrain.

Reads the same elevation tiles the 3D map draws its terrain from (Terrarium PNG tiles on AWS Open
Data, https://registry.opendata.aws/terrain-tiles/), samples the pixel under each located plant in
data/plants.json and writes data/elevation.json: {"lat,lon": metres above sea level}.

Run from the project root after build_data.py:  python3 scripts/build_elevation.py
"""
import io
import json
import math
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
TILES = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
ZOOM = 10  # about 150 m per pixel at Romania's latitude


def tile_pixel(lat, lon, z):
    n = 2 ** z
    x = (lon + 180) / 360 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return int(x), int(y), int((x % 1) * 256), int((y % 1) * 256)


def main():
    plants = json.loads((ROOT / "data" / "plants.json").read_text(encoding="utf-8"))["plants"]
    points = {f'{p["lat"]},{p["lon"]}' for p in plants if p["lat"] is not None}
    dc_path = ROOT / "data" / "datacenters.json"  # data centres stand on the terrain too
    if dc_path.exists():
        sites = json.loads(dc_path.read_text(encoding="utf-8"))["sites"]
        points |= {f'{d["lat"]},{d["lon"]}' for d in sites if d["lat"] is not None}
    tiles, out = {}, {}
    for key in sorted(points):
        lat, lon = map(float, key.split(","))
        tx, ty, px, py = tile_pixel(lat, lon, ZOOM)
        if (tx, ty) not in tiles:
            with urllib.request.urlopen(TILES.format(z=ZOOM, x=tx, y=ty), timeout=60) as r:
                tiles[(tx, ty)] = Image.open(io.BytesIO(r.read())).convert("RGB")
        red, green, blue = tiles[(tx, ty)].getpixel((px, py))
        out[key] = round(red * 256 + green + blue / 256 - 32768)  # Terrarium encoding
    path = ROOT / "data" / "elevation.json"
    path.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"elevation.json: {len(out)} points from {len(tiles)} tiles, "
          f"{min(out.values())}-{max(out.values())} m")


if __name__ == "__main__":
    main()
