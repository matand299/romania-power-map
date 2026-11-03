"""Generate simple placeholder 3D models (glTF binary) for each technology on the 3D map.

Each model is built from primitives, in white, so the map tints it with the technology's colour from
assets/theme.json. They are stand-ins: replace any file in assets/models/ with a designed model of
the same name (Y up, about 10 units tall, origin at the base) and the map uses it as it is.

Run from the project root:  python3 scripts/build_models.py
"""
import math
from pathlib import Path

import numpy as np
import trimesh
from trimesh.creation import box, cone, cylinder, icosphere
from trimesh.transformations import rotation_matrix, translation_matrix

OUT = Path(__file__).resolve().parent.parent / "assets" / "models"


def at(mesh, x=0.0, y=0.0, z=0.0):
    """Move a mesh; y is up (glTF)."""
    mesh.apply_transform(translation_matrix([x, y, z]))
    return mesh


def up(mesh):
    """trimesh builds cylinders and cones along z; turn them to stand along y."""
    mesh.apply_transform(rotation_matrix(-math.pi / 2, [1, 0, 0]))
    return mesh


def column(radius, height, x=0.0, z=0.0, sections=24):
    return at(up(cylinder(radius=radius, height=height, sections=sections)), x, height / 2, z)


def frustum(r_bottom, r_top, height, x=0.0, y=0.0, z=0.0, sections=28):
    """A cylinder whose top ring is scaled to r_top: a truncated cone, base at y."""
    mesh = up(cylinder(radius=r_bottom, height=height, sections=sections))
    top = mesh.vertices[:, 1] > 0
    mesh.vertices[top, 0] *= r_top / r_bottom
    mesh.vertices[top, 2] *= r_top / r_bottom
    return at(mesh, x, y + height / 2, z)


def cooling_tower(x, z, height=7.0):
    # A waisted tower: a tapering lower part under a slightly flaring top.
    return [frustum(2.0, 1.3, height * 0.7, x=x, z=z), frustum(1.3, 1.45, height * 0.3, x=x, y=height * 0.7, z=z)]


def wind():
    parts = [column(0.22, 9.0), at(box([1.4, 0.5, 0.5]), 0.3, 9.1, 0)]
    for k in range(3):
        blade = at(box([0.18, 4.2, 0.05]), 0, 2.1, 0)
        blade.apply_transform(rotation_matrix(k * 2 * math.pi / 3, [0, 0, 1]))
        parts.append(at(blade, -0.45, 9.1, 0.3))
    return parts


def solar():
    parts = []
    for row in range(3):
        panel = box([6.0, 0.12, 1.6])
        panel.apply_transform(rotation_matrix(math.radians(30), [1, 0, 0]))
        parts.append(at(panel, 0, 1.1, (row - 1) * 2.4))
        for side in (-2.6, 2.6):
            parts.append(at(box([0.12, 1.0, 0.12]), side, 0.5, (row - 1) * 2.4))
    return parts


def storage():
    parts = []
    for i in range(3):
        parts.append(at(box([1.8, 1.7, 4.6]), (i - 1) * 2.3, 0.85, 0))
        parts.append(at(box([1.2, 0.35, 1.2]), (i - 1) * 2.3, 1.85, 1.2))
    return parts


def hydro():
    wall = box([9.0, 4.5, 1.6])
    # Slope the downstream face: shear the wall so its top is thinner than its base.
    wall.vertices[:, 2] += np.where(wall.vertices[:, 1] > 0, -0.5, 0.0)
    return [at(wall, 0, 2.25, 0), at(box([2.2, 1.6, 2.2]), 0, 0.8, 2.0)]


def gas():
    return [at(box([4.5, 2.6, 3.0]), 0, 1.3, 0), column(0.35, 7.0, x=1.6, z=-0.6), column(0.35, 7.0, x=2.4, z=-0.6)]


def coal():
    return [at(box([4.0, 3.0, 3.0]), -1.5, 1.5, 0), column(0.45, 10.0, x=0.8, z=-1.0),
            *cooling_tower(3.6, 1.2, height=6.5)]


def nuclear():
    dome = icosphere(subdivisions=3, radius=1.8)
    dome.vertices[:, 1] = np.maximum(dome.vertices[:, 1], 0)  # flatten the lower half: a dome
    return [*cooling_tower(-2.8, 0, height=8.0), *cooling_tower(1.8, 2.2, height=8.0),
            column(1.8, 2.2, x=1.4, z=-2.4), at(dome, 1.4, 2.2, -2.4)]


def other():
    house = at(box([3.6, 2.2, 3.0]), 0, 1.1, 0)
    roof = at(up(cone(radius=2.6, height=1.6, sections=4)), 0, 2.2, 0)
    roof.apply_transform(rotation_matrix(math.pi / 4, [0, 1, 0]))
    return [house, roof, column(0.25, 4.5, x=1.2, z=-0.9)]


MODELS = {"solar": solar, "wind": wind, "hydro": hydro, "gas": gas, "coal": coal,
          "nuclear": nuclear, "storage": storage, "other": other}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    white = trimesh.visual.material.PBRMaterial(baseColorFactor=[255, 255, 255, 255], metallicFactor=0.0,
                                                roughnessFactor=0.75)
    for name, build in MODELS.items():
        mesh = trimesh.util.concatenate(build())
        mesh.visual = trimesh.visual.TextureVisuals(material=white)
        path = OUT / f"{name}.glb"
        mesh.export(path)
        lo, hi = mesh.bounds
        print(f"{path.name}: {len(mesh.faces)} faces, {path.stat().st_size // 1024} KB, "
              f"size {hi[0] - lo[0]:.1f} x {hi[1] - lo[1]:.1f} x {hi[2] - lo[2]:.1f}")


if __name__ == "__main__":
    main()
