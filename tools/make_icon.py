"""Draws the DBS_SplatTrain node icon (24 and 48 px): soft Gaussian splats in a tracked camera's
view frame. python tools/make_icon.py -> nuke/DBS_SplatTrain.png and nuke/DBS_SplatTrain@2x.png"""

import math
import os

import numpy as np
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = 384                                   # drawn big, scaled down

# (x, y, sx, sy, angle deg, rgb, opacity) in 0-1 icon units
SPLATS = [
    (0.36, 0.60, 0.20, 0.11, 25, (255, 140, 60), 0.95),
    (0.60, 0.42, 0.18, 0.10, -30, (70, 170, 255), 0.95),
    (0.62, 0.66, 0.13, 0.08, 60, (255, 205, 70), 0.9),
    (0.40, 0.38, 0.12, 0.07, -10, (120, 230, 150), 0.9),
    (0.50, 0.53, 0.09, 0.06, 45, (255, 255, 255), 0.85),
    (0.72, 0.30, 0.07, 0.05, 0, (200, 120, 255), 0.8),
]


def draw(size):
    yy, xx = np.mgrid[0:S, 0:S] / float(S)
    rgb = np.zeros((S, S, 3))
    rgb[:] = (28, 32, 44)
    for x, y, sx, sy, ang, col, op in SPLATS:
        a = math.radians(ang)
        dx, dy = xx - x, yy - y
        u = dx * math.cos(a) + dy * math.sin(a)
        v = -dx * math.sin(a) + dy * math.cos(a)
        w = op * np.exp(-0.5 * ((u / (sx / 2)) ** 2 + (v / (sy / 2)) ** 2))[..., None]
        rgb = rgb * (1 - w) + np.array(col) * w
    img = Image.fromarray(rgb.clip(0, 255).astype(np.uint8)).convert("RGBA")
    d = ImageDraw.Draw(img)
    m, L, lw = int(0.10 * S), int(0.22 * S), max(4, S // 40)
    for cx, cy, sxn, syn in ((m, m, 1, 1), (S - m, m, -1, 1), (m, S - m, 1, -1), (S - m, S - m, -1, -1)):
        d.line([(cx, cy + syn * L), (cx, cy), (cx + sxn * L, cy)], fill=(235, 240, 250, 255), width=lw)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=S // 6, fill=255)
    img.putalpha(mask)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    draw(24).save(os.path.join(ROOT, "nuke", "DBS_SplatTrain.png"))
    draw(48).save(os.path.join(ROOT, "nuke", "DBS_SplatTrain@2x.png"))
    draw(256).save(os.path.join(ROOT, "docs", "icon_256.png")) if os.path.isdir(os.path.join(ROOT, "docs")) else None
    print("ok")
