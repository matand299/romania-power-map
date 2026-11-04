"""Generate the 3D models (glTF binary) for each technology on the 3D map.

Toy-like models built from primitives: concrete buildings with window strips, red-and-white chimneys,
blue solar cells, white turbines, a dam with spillways. Every colour comes from assets/theme.json:
the parts from "models" -> "palette", and the coloured rim around each model's base from the
technology's colour in "tech". After changing those colours, run this script again.

Any file in assets/models/ can be replaced with a designed model of the same name (Y up, about
10 units across, origin at the centre of its base) and the map uses it as it is.

Each technology gets two files: <name>.glb (detailed, used close up) and <name>_low.glb (light, used
from afar so the map stays fast).

Run from the project root:  python3 scripts/build_models.py
"""
import json
import math
from pathlib import Path

import numpy as np
import trimesh
from trimesh.creation import box, cylinder, icosphere, revolve
from trimesh.transformations import rotation_matrix, translation_matrix

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "models"
THEME = json.loads((ROOT / "assets" / "theme.json").read_text(encoding="utf-8"))
PALETTE = THEME["models"]["palette"]
PLATE_TOP = 0.45  # everything stands on the base plate, whose top is at this height
# Each model is built twice: in detail (seen close up) and light (<name>_low.glb, seen from afar, with
# no windows, rails or solar cells and few facets). main() switches LOW between the two builds.
LOW = False


def sec(n):
    """Facets around a round part: fewer in the light version."""
    return max(6, n // 3) if LOW else max(8, n * 2 // 3)


# ---- primitives (y is up, as in glTF) -------------------------------------------------------

def at(mesh, x=0.0, y=0.0, z=0.0):
    mesh.apply_transform(translation_matrix([x, y, z]))
    return mesh


def turn(mesh, degrees, axis):
    mesh.apply_transform(rotation_matrix(math.radians(degrees), axis))
    return mesh


def up(mesh):
    """trimesh builds cylinders along z; stand them along y."""
    return turn(mesh, -90, [1, 0, 0])


def block(w, h, d, x=0.0, y=PLATE_TOP, z=0.0):
    """A box standing on y."""
    return at(box([w, h, d]), x, y + h / 2, z)


def column(r, h, x=0.0, y=PLATE_TOP, z=0.0, sections=24):
    return at(up(cylinder(radius=r, height=h, sections=sec(sections))), x, y + h / 2, z)


def frustum(r0, r1, h, x=0.0, y=PLATE_TOP, z=0.0, sections=28):
    """A cylinder whose top ring is scaled to r1."""
    mesh = up(cylinder(radius=r0, height=h, sections=sec(sections)))
    top = mesh.vertices[:, 1] > 0
    mesh.vertices[top, 0] *= r1 / r0
    mesh.vertices[top, 2] *= r1 / r0
    return at(mesh, x, y + h / 2, z)


def dome(r, x=0.0, y=PLATE_TOP, z=0.0):
    mesh = icosphere(subdivisions=1 if LOW else 2, radius=r)
    mesh.vertices[:, 1] = np.maximum(mesh.vertices[:, 1], 0)
    return at(mesh, x, y, z)


def puff(r, x, y, z):
    return at(icosphere(subdivisions=0 if LOW else 1, radius=r), x, y, z)


# ---- recurring pieces: each returns a list of (mesh, palette key) ---------------------------

def plate(w, d, rim_color):
    """A rounded base plate on a thin rim in the technology's colour."""
    def rounded(w, d, h, y, r):
        if LOW:  # square corners from afar
            return [at(box([w, h, d]), 0, y + h / 2, 0)]
        return [at(box([w - 2 * r, h, d]), 0, y + h / 2, 0), at(box([w, h, d - 2 * r]), 0, y + h / 2, 0),
                *[at(up(cylinder(radius=r, height=h, sections=sec(16))), sx * (w / 2 - r), y + h / 2, sz * (d / 2 - r))
                  for sx in (-1, 1) for sz in (-1, 1)]]
    return ([(m, rim_color) for m in rounded(w + 0.3, d + 0.3, 0.2, 0, 0.7)]
            + [(m, "base") for m in rounded(w, d, PLATE_TOP - 0.2, 0.2, 0.6)])


def windows(w, h, d, x, y, z, rows, cols):
    """Rows of windows on the front (+z) and right (+x) faces of a block at (x, y, z)."""
    out = []
    if LOW:
        return out
    for i in range(rows):
        wy = y + h * (i + 0.6) / (rows + 0.2)
        for j in range(cols):
            out.append((at(box([w / cols * 0.62, h / rows * 0.42, 0.06]), x - w / 2 + w * (j + 0.5) / cols, wy, z + d / 2 + 0.02), "window"))
        for j in range(max(1, round(cols * d / w))):
            n = max(1, round(cols * d / w))
            out.append((at(box([0.06, h / rows * 0.42, d / n * 0.62]), x + w / 2 + 0.02, wy, z - d / 2 + d * (j + 0.5) / n), "window"))
    return out


def building(w, h, d, x=0.0, z=0.0, rows=2, cols=3, trim="red"):
    """A concrete block with windows, a coloured roof trim and a few roof units."""
    out = [(block(w, h, d, x, PLATE_TOP, z), "concrete"),
           (block(w + 0.12, 0.22, d + 0.12, x, PLATE_TOP + h, z), trim)]
    if LOW:
        return out
    out += [
           (block(w * 0.25, 0.3, d * 0.3, x - w * 0.2, PLATE_TOP + h + 0.22, z), "metal"),
           (block(w * 0.2, 0.3, d * 0.25, x + w * 0.22, PLATE_TOP + h + 0.22, z - d * 0.15), "metal")]
    return out + windows(w, h, d, x, PLATE_TOP, z, rows, cols)


def chimney(x, z, h, r=0.32, bands=6, smoke=True):
    """A red-and-white striped chimney, narrowing upwards, with a puff of smoke."""
    out, step = [], h / bands
    for i in range(bands):
        r0, r1 = r * (1 - 0.18 * i / bands), r * (1 - 0.18 * (i + 1) / bands)
        out.append((frustum(r0, r1, step, x, PLATE_TOP + i * step, z, sections=sec(20)), "red" if i % 2 else "white"))
    top = PLATE_TOP + h
    out.append((column(r * 0.95, 0.12, x, top, z, sections=sec(20)), "metal"))
    if smoke:
        out += [(puff(r * 1.6, x + r * 0.6, top + r * 2.0, z), "steam")] if LOW else [
            (puff(r * 1.3, x, top + r * 1.3, z), "steam"), (puff(r * 1.6, x + r * 1.2, top + r * 2.8, z - r * 0.3), "steam"),
            (puff(r * 1.9, x + r * 2.8, top + r * 4.4, z - r * 0.6), "steam")]
    return out


def cooling_tower(x, z, h, r, steam=True):
    """A hyperbolic cooling tower on a ring of legs, with steam rising from it."""
    t = np.linspace(0, 1, 14)
    waist = 0.62
    radius = r * (waist + (1 - waist) * ((t - 0.72) / 0.72) ** 2)
    radius[-1] = radius[-2] * 1.02
    profile = np.column_stack([radius, t * h * 0.9])
    shell = up(revolve(profile, sections=sec(32)))
    out = [(at(shell, x, PLATE_TOP + h * 0.1, z), "concrete")]
    for k in range(0 if LOW else 12):
        a = 2 * math.pi * k / 12
        leg = block(0.14, h * 0.1, 0.14, x + r * 0.92 * math.cos(a), PLATE_TOP, z + r * 0.92 * math.sin(a))
        out.append((leg, "concrete_dark"))
    out.append((column(r * 0.9, 0.08, x, PLATE_TOP + h * 0.1 - 0.04, z, sections=sec(32)), "concrete_dark"))
    if steam:
        top = PLATE_TOP + h
        tr = radius[-1]
        out += [(puff(tr * 0.9, x, top + tr * 0.5, z), "steam"), (puff(tr * 0.75, x + tr * 0.6, top + tr * 1.2, z + tr * 0.2), "steam"),
                (puff(tr * 0.7, x - tr * 0.5, top + tr * 1.1, z - tr * 0.3), "steam")]
    return out


def tank(x, z, r, h):
    if LOW:
        return [(column(r, h * 1.3, x, PLATE_TOP, z), "tank")]
    return [(column(r, h, x, PLATE_TOP, z), "tank"), (dome(r, x, PLATE_TOP + h, z), "tank"),
            (column(r * 1.01, 0.12, x, PLATE_TOP + h * 0.5, z), "metal")]


# ---- the models ----------------------------------------------------------------------------

def solar(rim):
    out = plate(10, 8, rim)
    for row in range(3):
        for col in range(2):
            px, pz = (col - 0.5) * 4.6, (row - 1) * 2.5
            parts = [(box([4.2, 0.14, 1.9]), "panel")] if LOW else [(box([4.2, 0.1, 1.9]), "panel_frame")]
            for i in range(0 if LOW else 4):
                for j in range(2):
                    parts.append((at(box([0.92, 0.06, 0.82]), -1.575 + i * 1.05, 0.07, -0.45 + j * 0.9), "panel"))
            for m, c in parts:
                turn(m, 25, [1, 0, 0])
                out.append((at(m, px, PLATE_TOP + 1.05, pz), c))
            for sx in (() if LOW else (-1.6, 1.6)):
                out.append((block(0.12, 0.9, 0.12, px + sx, PLATE_TOP, pz), "metal"))
    out.append((block(1.0, 0.9, 0.8, 4.2, PLATE_TOP, 3.4), "concrete"))  # inverter
    return out


def wind(rim):
    out = plate(5, 5, rim)
    out.append((frustum(0.38, 0.17, 7.2, sections=sec(24)), "white"))
    hub_y = PLATE_TOP + 7.35
    out.append((at(box([0.55, 0.55, 1.5]), 0, hub_y, -0.25), "white"))
    out.append((at(up(cylinder(radius=0.22, height=0.4, sections=sec(20))), 0, hub_y, 0.62), "white"))
    for k in range(3):
        blade = box([0.42, 3.6, 0.07])
        top = blade.vertices[:, 1] > 0
        blade.vertices[top, 0] *= 0.3
        at(blade, 0.08, 1.95, 0)
        turn(blade, 90 + k * 120, [0, 0, 1])
        out.append((at(blade, 0, hub_y, 0.72), "white"))
    return out


def hydro(rim):
    out = plate(10, 9, rim)
    out.append((block(9.6, 0.25, 4.0, 0, PLATE_TOP, 2.3), "water_deep"))  # tailwater pool
    body = box([9.0, 4.6, 3.4])
    front_top = (body.vertices[:, 1] > 0) & (body.vertices[:, 2] > 0)
    body.vertices[front_top, 2] -= 1.6  # the downstream (+z) face slopes back
    out.append((at(body, 0, PLATE_TOP + 2.3, -1.4), "dam"))
    slope = -math.degrees(math.atan2(1.6, 4.6))
    for i in range(3):  # spillways down the sloped face, between piers
        chute = turn(box([2.0, 4.9, 0.12]), slope, [1, 0, 0])
        out.append((at(chute, -2.7 + i * 2.7, PLATE_TOP + 2.3, -0.42), "water"))
        if not LOW:  # spray at the foot of each spillway
            out.append((puff(0.55, -2.7 + i * 2.7 - 0.5, PLATE_TOP + 0.35, 0.9), "steam"))
            out.append((puff(0.5, -2.7 + i * 2.7 + 0.5, PLATE_TOP + 0.3, 1.1), "steam"))
    for x in (-4.05, -1.35, 1.35, 4.05):
        pier = turn(box([0.6, 5.0, 0.6]), slope, [1, 0, 0])
        out.append((at(pier, x, PLATE_TOP + 2.45, -0.3), "concrete"))
    deck_y = PLATE_TOP + 4.9
    out.append((block(9.6, 0.3, 2.2, 0, deck_y, -2.0), "concrete"))
    for z in (-3.05, -0.95):
        out.append((block(9.4, 0.06, 0.06, 0, deck_y + 0.75, z), "rail"))
        for x in ([] if LOW else np.linspace(-4.6, 4.6, 10)):
            out.append((block(0.06, 0.75, 0.06, x, deck_y + 0.3, z), "rail"))
    for x in (-2.0, 2.0):
        out.append((column(0.35, 0.6, x, deck_y + 0.3, -2.0), "rail"))
    for x in (-4.0, 4.0):  # gate hoists
        out.append((block(1.3, 1.0, 1.6, x, deck_y + 0.3, -2.0), "dam"))
        hoist = at(turn(cylinder(radius=0.4, height=1.4, sections=sec(20)), 90, [0, 1, 0]), x, deck_y + 1.7, -2.0)
        out.append((hoist, "dam"))
    return out


def gas(rim):
    out = plate(10, 8, rim)
    out += building(4.6, 3.4, 3.2, x=-1.6, z=-0.8, rows=2, cols=4)
    out += building(2.6, 2.0, 2.4, x=2.4, z=1.6, rows=1, cols=2)
    out += chimney(2.2, -2.2, 7.5, r=0.42)
    out += tank(-3.4, 2.6, 0.6, 1.0) + tank(-2.0, 2.6, 0.6, 1.0) + tank(-0.6, 2.6, 0.6, 1.0)
    out.append((at(turn(cylinder(radius=0.12, height=3.0, sections=sec(12)), 90, [0, 1, 0]), 0.9, PLATE_TOP + 1.3, -0.1), "pipe"))
    return out


def coal(rim):
    out = plate(11, 9, rim)
    out += cooling_tower(-3.4, -1.6, 5.5, 1.5, steam=False)
    out += building(2.4, 4.6, 2.6, x=1.0, z=-1.6, rows=4, cols=2)
    out += building(2.4, 4.6, 2.6, x=3.6, z=-1.6, rows=4, cols=2)
    out += building(5.4, 1.6, 2.4, x=1.6, z=1.6, rows=1, cols=4)
    for x in (0.6, 2.3, 4.0):
        out += chimney(x, -3.4, 8.0, r=0.34)
    out += tank(-1.6, 2.6, 0.5, 0.8) + tank(-3.0, 2.6, 0.5, 0.8)
    return out


def nuclear(rim):
    out = plate(11, 9, rim)
    out += cooling_tower(-3.0, -1.4, 7.0, 1.9)
    out += cooling_tower(0.9, -2.0, 7.0, 1.9)
    out.append((column(1.3, 2.4, 3.6, PLATE_TOP, 1.6), "concrete"))
    out.append((dome(1.3, 3.6, PLATE_TOP + 2.4, 1.6), "white"))
    out.append((column(1.32, 0.18, 3.6, PLATE_TOP + 2.2, 1.6), "red"))
    out += building(3.2, 1.8, 2.0, x=-0.2, z=2.6, rows=1, cols=3)
    return out


def storage(rim):
    out = plate(9, 7, rim)
    for i in range(3):
        for j in range(2):
            x, z = -2.6 + i * 2.5, -1.3 + j * 2.8
            out.append((block(2.0, 1.6, 2.2, x, PLATE_TOP, z), "battery"))
            out.append((block(2.04, 0.18, 2.24, x, PLATE_TOP + 1.0, z), "battery_accent"))
            if LOW:
                continue
            out.append((block(0.8, 0.25, 0.8, x, PLATE_TOP + 1.6, z), "metal"))
            for k in range(3):
                out.append((block(0.06, 0.6, 0.3, x + 1.02, PLATE_TOP + 0.3, z - 0.6 + k * 0.6), "window"))
    out.append((block(1.2, 1.5, 1.4, 3.5, PLATE_TOP, 2.4), "metal"))  # transformer
    for k in range(0 if LOW else 4):
        out.append((block(0.08, 1.2, 1.2, 2.95 - 0.08, PLATE_TOP + 0.1, 2.4 - 0.45 + k * 0.3), "concrete_dark"))
    return out


def other(rim):
    out = plate(7, 6, rim)
    out += building(3.6, 2.4, 2.8, x=-0.6, z=0.3, rows=2, cols=3, trim="battery_accent")
    out += chimney(2.0, -1.4, 5.0, r=0.3, bands=4)
    out += tank(2.2, 1.8, 0.5, 0.9)
    return out


def datacenter(rim):
    """A data-centre hall: a long white block with a blue band and doors, a row of cooling fans on the roof,
    backup generators in containers along one side and a small fuel tank."""
    out = plate(11, 8, rim)
    hall_w, hall_h, hall_d = 7.6, 3.0, 4.6
    out.append((block(hall_w, hall_h, hall_d, -0.6, PLATE_TOP, -0.6), "white"))
    out.append((block(hall_w + 0.1, 0.35, hall_d + 0.1, -0.6, PLATE_TOP + 1.2, -0.6), "window"))  # blue band
    out.append((block(hall_w + 0.16, 0.18, hall_d + 0.16, -0.6, PLATE_TOP + hall_h, -0.6), "metal"))  # roof edge
    if not LOW:
        for x in (-3.4, -2.6):  # doors on the front
            out.append((block(0.6, 1.1, 0.06, x, PLATE_TOP, -0.6 + hall_d / 2 + 0.02), "metal"))
    # Cooling units on the roof: boxes with a round fan on top.
    for i in range(4 if LOW else 6):
        n = 4 if LOW else 6
        x = -0.6 - hall_w / 2 + 0.9 + i * (hall_w - 1.8) / (n - 1)
        for z in (-1.6, 0.4):
            y = PLATE_TOP + hall_h + 0.18
            out.append((block(1.0, 0.45, 1.0, x, y, z), "concrete"))
            out.append((column(0.36, 0.08, x, y + 0.45, z, sections=20), "pipe"))
    # Backup generators: containers along the right-hand side, each with a short exhaust stack.
    for j in range(3):
        z = -2.4 + j * 1.9
        out.append((block(1.4, 1.2, 1.5, 4.1, PLATE_TOP, z), "battery"))
        out.append((block(1.42, 0.16, 1.52, 4.1, PLATE_TOP + 0.75, z), "battery_accent"))
        if not LOW:
            out.append((column(0.1, 0.6, 4.4, PLATE_TOP + 1.2, z - 0.4, sections=10), "metal"))
    out += tank(4.0, 3.2, 0.45, 0.9)
    return out


MODELS = {"solar": solar, "wind": wind, "hydro": hydro, "gas": gas, "coal": coal,
          "nuclear": nuclear, "storage": storage, "other": other, "datacenter": datacenter}


def material(hex_color):
    rgb = [int(hex_color[i:i + 2], 16) for i in (1, 3, 5)]
    return trimesh.visual.material.PBRMaterial(baseColorFactor=[*rgb, 255], metallicFactor=0.0, roughnessFactor=0.85)


def main():
    global LOW
    OUT.mkdir(parents=True, exist_ok=True)
    for LOW in (False, True):
        for name, build in MODELS.items():
            export(name, build)


def export(name, build):
    if True:
        rim = f"rim:{(THEME['tech'].get(name) or THEME['datacenters'])['color']}"
        by_color = {}
        for mesh, key in build(rim):
            by_color.setdefault(key, []).append(mesh)
        scene = trimesh.Scene()
        for key, meshes in by_color.items():
            mesh = trimesh.util.concatenate(meshes)
            mesh.visual = trimesh.visual.TextureVisuals(material=material(key[4:] if key.startswith("rim:") else PALETTE[key]))
            scene.add_geometry(mesh, node_name=key.replace(":", "_").replace("#", ""))
        path = OUT / f"{name}{'_low' if LOW else ''}.glb"
        path.write_bytes(scene.export(file_type="glb"))
        lo, hi = scene.bounds
        faces = sum(len(g.faces) for g in scene.geometry.values())
        print(f"{path.name}: {faces} faces, {path.stat().st_size // 1024} KB, "
              f"size {hi[0] - lo[0]:.1f} x {hi[1] - lo[1]:.1f} x {hi[2] - lo[2]:.1f}")


if __name__ == "__main__":
    main()
