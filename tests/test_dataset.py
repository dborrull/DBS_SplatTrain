"""Plain-Python checks of the camera conversions (python tests/test_dataset.py)."""

import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nuke"))
from dbs_splattrain import dataset  # noqa: E402


def rot_y(deg):
    a = math.radians(deg)
    return [[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]]


def project_colmap(cam, p):
    """World point -> pixel through the COLMAP pose and PINHOLE intrinsics."""
    q, t = dataset.colmap_pose(cam)
    w, x, y, z = q
    r = [[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
         [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
         [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]]
    pc = [sum(r[i][k] * p[k] for k in range(3)) + t[i] for i in range(3)]
    fx, fy, cx, cy = dataset.intrinsics(cam)
    return fx * pc[0] / pc[2] + cx, fy * pc[1] / pc[2] + cy, pc[2]


def test_center_and_axes():
    # Camera at (1, 2, 5) turned 30 deg about Y; a point straight ahead lands on the centre.
    cam = {"name": "a.png", "r": rot_y(30), "t": [1, 2, 5], "focal": 35.0, "haperture": 36.0,
           "win_translate": [0, 0], "width": 1920, "height": 1080}
    fwd = [-cam["r"][i][2] for i in range(3)]          # Nuke cameras look down -Z
    up = [cam["r"][i][1] for i in range(3)]
    ahead = [cam["t"][i] + 4 * fwd[i] for i in range(3)]
    u, v, d = project_colmap(cam, ahead)
    assert abs(u - 960) < 1e-6 and abs(v - 540) < 1e-6 and abs(d - 4) < 1e-9, (u, v, d)
    # A point above the view axis is in the top half of the image (OpenCV y down).
    _, v_up, _ = project_colmap(cam, [ahead[i] + 0.5 * up[i] for i in range(3)])
    assert v_up < 540, v_up


if __name__ == "__main__":
    test_center_and_axes()
    print("ok")
