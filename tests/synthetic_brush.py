"""Synthetic check of the dataset writer against Brush (numpy + Pillow, no Nuke).

python tests/synthetic_brush.py <out_dir> [--brush bin/brush-v0.3.0/brush_app.exe] [--steps 3000]

Builds a coloured box away from the origin, Nuke-convention cameras on an arc around it, renders
them by point splatting, writes the dataset with dataset.write_colmap (box corners and edge
samples as points3D) and trains Brush on it. Then reports where the trained splats are compared
with the box: if Brush keeps the input world, their centre and extent match it.
"""

import argparse
import math
import os
import struct
import subprocess
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nuke"))
from dbs_splattrain import dataset  # noqa: E402

CENTER = np.array([5.0, 1.0, -3.0])
SIZE = np.array([2.0, 1.2, 1.6])
W, H = 320, 240


def box_points(n_side=220):
    """Dense points on the box faces, coloured by a checker per face."""
    pts, cols = [], []
    face_rgb = [(220, 60, 50), (60, 200, 80), (50, 90, 220), (230, 200, 40), (200, 60, 200), (40, 200, 210)]
    g = (np.arange(n_side) + 0.5) / n_side - 0.5
    a, b = np.meshgrid(g, g)
    a, b = a.ravel(), b.ravel()
    k = 0
    for axis in range(3):
        for sign in (-0.5, 0.5):
            p = np.zeros((a.size, 3))
            o = [i for i in range(3) if i != axis]
            p[:, axis] = sign
            p[:, o[0]], p[:, o[1]] = a, b
            checker = ((np.floor((a + 0.5) * 6) + np.floor((b + 0.5) * 6)) % 2)[:, None]
            c = np.array(face_rgb[k]) * (0.55 + 0.45 * checker)
            pts.append(p * SIZE + CENTER)
            cols.append(c)
            k += 1
    return np.concatenate(pts), np.concatenate(cols).astype(np.uint8)


def look_at(eye, target):
    """Nuke camera rotation: columns = camera X, Y, Z in world, looking down -Z."""
    z = eye - target
    z /= np.linalg.norm(z)
    x = np.cross([0.0, 1.0, 0.0], z)
    x /= np.linalg.norm(x)
    return np.stack([x, np.cross(z, x), z], axis=1)


def render(cam, pts, cols):
    fx, fy, cx, cy = dataset.intrinsics(cam)
    r, t = np.array(cam["r"]), np.array(cam["t"])
    pc = (pts - t) @ r                       # camera coords (Nuke axes)
    d = -pc[:, 2]
    ok = d > 1e-3
    u = (fx * pc[ok, 0] / d[ok] + cx).astype(int)
    v = (-fy * pc[ok, 1] / d[ok] + cy).astype(int)
    c, dd = cols[ok], d[ok]
    inside = (u >= 0) & (u < W) & (v >= 0) & (v < H)
    u, v, c, dd = u[inside], v[inside], c[inside], dd[inside]
    # Noisy dark background: Brush v0.3.0 cannot load image files under 16 KB ("early eof").
    img = np.random.default_rng(len(pts)).integers(0, 40, (H, W, 3)).astype(np.uint8)
    order = np.argsort(-dd)                  # far first, near overwrites
    img[v[order], u[order]] = c[order]
    return img


def read_ply_xyz_opacity(path):
    with open(path, "rb") as f:
        props, n = [], 0
        while True:
            line = f.readline().decode("ascii", "replace").strip()
            if line.startswith("element vertex"):
                n = int(line.split()[2])
            elif line.startswith("property"):
                props.append((line.split()[1], line.split()[2]))
            elif line == "end_header":
                break
        fmt = {"float": "f", "uchar": "B", "double": "d", "int": "i", "uint": "I"}
        rec = "<" + "".join(fmt[t] for t, _ in props)
        data = np.frombuffer(f.read(n * struct.calcsize(rec)),
                             dtype=np.dtype([(name, "<" + fmt[t].replace("B", "u1")) for t, name in props]))
    xyz = np.stack([data["x"], data["y"], data["z"]], 1).astype(np.float64)
    return xyz, 1.0 / (1.0 + np.exp(-data["opacity"].astype(np.float64)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--brush", default=os.path.join("bin", "brush-v0.3.0", "brush_app.exe"))
    ap.add_argument("--steps", type=int, default=3000)
    a = ap.parse_args()
    data_dir = os.path.join(os.path.abspath(a.out_dir), "dataset")
    os.makedirs(os.path.join(data_dir, "images"), exist_ok=True)

    pts, cols = box_points()
    cams = []
    for i in range(36):
        ang = math.radians(-70 + 140 * i / 35.0)
        eye = CENTER + np.array([5.0 * math.sin(ang), 1.5 + 0.8 * math.sin(3 * ang), 5.0 * math.cos(ang)])
        cam = {"name": "frame_%04d.png" % (1001 + i), "r": look_at(eye, CENTER).tolist(), "t": eye.tolist(),
               "focal": 30.0, "haperture": 36.0, "win_translate": [0.0, 0.0], "width": W, "height": H}
        Image.fromarray(render(cam, pts, cols)).save(os.path.join(data_dir, "images", cam["name"]))
        cams.append(cam)
    init = pts[:: max(1, len(pts) // 3000)]
    init_c = cols[:: max(1, len(pts) // 3000)]
    dataset.write_colmap(data_dir, cams, init.tolist(), init_c.tolist())
    print("dataset:", data_dir, "| cameras", len(cams), "| init points", len(init))

    export = os.path.join(os.path.abspath(a.out_dir), "exports")
    os.makedirs(export, exist_ok=True)
    cmd = [os.path.abspath(a.brush), data_dir, "--total-steps", str(a.steps), "--export-every", str(a.steps),
           "--export-path", export, "--export-name", "export_{iter}.ply", "--eval-every", "100000"]
    print(" ".join(cmd))
    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True)
    print("brush exit %d in %.1f s" % (res.returncode, time.time() - t0))
    print((res.stdout + res.stderr)[-2000:])

    plys = sorted(f for f in os.listdir(export) if f.endswith(".ply"))
    if not plys:
        sys.exit("no ply exported")
    xyz, op = read_ply_xyz_opacity(os.path.join(export, plys[-1]))
    solid = xyz[op > 0.5]
    print("ply %s: %d splats, %d with opacity > 0.5" % (plys[-1], len(xyz), len(solid)))
    print("box centre      ", CENTER, " size", SIZE)
    print("splat median    ", np.round(np.median(solid, 0), 3))
    print("splat 2-98% size ", np.round(np.percentile(solid, 98, 0) - np.percentile(solid, 2, 0), 3))
    near = np.abs((solid - CENTER) / (SIZE / 2)).max(1)
    print("share of solid splats within 10%% of the box: %.1f%%" % (100 * np.mean(near < 1.1)))
    # Result 2026-11-13 (Brush v0.3.0, 3000 steps, 20 s): 100 %, 2-98 % size = box size:
    # Brush keeps the input world (no recentring or rescaling).


main()
