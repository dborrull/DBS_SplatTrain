# DBS_SplatTrain - by David Borrull
# MIT License - Copyright (c) 2026 David Borrull. See LICENSE.
"""Nuke camera samples and tracker points -> a Brush dataset (COLMAP text or transforms.json).

Plain Python, no numpy and no `nuke` import, so it can be tested outside Nuke.

A camera sample is a dict: {"name": image file name, "r": 3x3 rotation (columns = camera axes in
world, Nuke convention: looks down -Z, Y up), "t": position, "focal", "haperture",
"win_translate": [x, y], "width", "height"} (focal and haperture in the same units, mm).
"""

import json
import math
import os
import struct


def intrinsics(cam):
    """-> (fx, fy, cx, cy) in pixels, square pixels. Principal point follows AutoProjection's
    xform.project_points (checked there against a real CameraTracker solve)."""
    w, h = float(cam["width"]), float(cam["height"])
    f = cam["focal"] / cam["haperture"] * w
    wx, wy = cam.get("win_translate", (0.0, 0.0))
    return f, f, w * (0.5 - wx / 2.0), h / 2.0 + wy * w / 2.0


def _transpose(a):
    return [[a[j][i] for j in range(3)] for i in range(3)]


def _matvec(a, v):
    return [sum(a[i][k] * v[k] for k in range(3)) for i in range(3)]


def _quat_wxyz(r):
    """Rotation matrix -> unit quaternion (w, x, y, z), w >= 0."""
    tr = r[0][0] + r[1][1] + r[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        q = (0.25 * s, (r[2][1] - r[1][2]) / s, (r[0][2] - r[2][0]) / s, (r[1][0] - r[0][1]) / s)
    elif r[0][0] > r[1][1] and r[0][0] > r[2][2]:
        s = math.sqrt(1.0 + r[0][0] - r[1][1] - r[2][2]) * 2
        q = ((r[2][1] - r[1][2]) / s, 0.25 * s, (r[0][1] + r[1][0]) / s, (r[0][2] + r[2][0]) / s)
    elif r[1][1] > r[2][2]:
        s = math.sqrt(1.0 + r[1][1] - r[0][0] - r[2][2]) * 2
        q = ((r[0][2] - r[2][0]) / s, (r[0][1] + r[1][0]) / s, 0.25 * s, (r[1][2] + r[2][1]) / s)
    else:
        s = math.sqrt(1.0 + r[2][2] - r[0][0] - r[1][1]) * 2
        q = ((r[1][0] - r[0][1]) / s, (r[0][2] + r[2][0]) / s, (r[1][2] + r[2][1]) / s, 0.25 * s)
    n = math.sqrt(sum(c * c for c in q))
    q = [c / n for c in q]
    return q if q[0] >= 0 else [-c for c in q]


def colmap_pose(cam):
    """Nuke camera -> COLMAP world-to-camera (quaternion wxyz, translation), OpenCV axes
    (x right, y down, z forward): flip the camera's Y and Z axes."""
    r = cam["r"]
    r_c2w = [[r[i][0], -r[i][1], -r[i][2]] for i in range(3)]
    r_w2c = _transpose(r_c2w)
    t = [-c for c in _matvec(r_w2c, cam["t"])]
    return _quat_wxyz(r_w2c), t


COLMAP_PINHOLE = 1


def write_colmap(out_dir, cams, points, colors=None, binary=True):
    """COLMAP model in out_dir/sparse/0: one PINHOLE camera per image (a zoom keeps its focal
    per frame), no 2D observations, tracker points as points3D (Brush's initial splats).
    Binary by default: Brush v0.3.0 fails on the text model ("early eof")."""
    d = os.path.join(out_dir, "sparse", "0")
    if not os.path.isdir(d):
        os.makedirs(d)
    if binary:
        _write_colmap_bin(d, cams, points, colors)
        return d
    with open(os.path.join(d, "cameras.txt"), "w", newline="\n") as f:
        f.write("# Written by DBS_SplatTrain\n# CAMERA_ID MODEL WIDTH HEIGHT PARAMS[]\n")
        for i, c in enumerate(cams, 1):
            f.write("%d PINHOLE %d %d %.6f %.6f %.6f %.6f\n" % ((i, c["width"], c["height"]) + intrinsics(c)))
    with open(os.path.join(d, "images.txt"), "w", newline="\n") as f:
        f.write("# IMAGE_ID QW QX QY QZ TX TY TZ CAMERA_ID NAME\n# POINTS2D[] (none)\n")
        for i, c in enumerate(cams, 1):
            q, t = colmap_pose(c)
            f.write("%d %s %s %d %s\n\n" % (i, " ".join("%.9f" % v for v in q),
                                            " ".join("%.9f" % v for v in t), i, c["name"]))
    with open(os.path.join(d, "points3D.txt"), "w", newline="\n") as f:
        f.write("# POINT3D_ID X Y Z R G B ERROR TRACK[]\n")
        for i, p in enumerate(points, 1):
            rgb = colors[i - 1] if colors else (128, 128, 128)
            f.write("%d %.6f %.6f %.6f %d %d %d 0\n" % ((i,) + tuple(p) + tuple(int(v) for v in rgb)))
    return d


def _write_colmap_bin(d, cams, points, colors):
    """COLMAP binary layout (little endian), as in COLMAP's read_write_model.py."""
    with open(os.path.join(d, "cameras.bin"), "wb") as f:
        f.write(struct.pack("<Q", len(cams)))
        for i, c in enumerate(cams, 1):
            f.write(struct.pack("<iiQQ4d", i, COLMAP_PINHOLE, int(c["width"]), int(c["height"]), *intrinsics(c)))
    with open(os.path.join(d, "images.bin"), "wb") as f:
        f.write(struct.pack("<Q", len(cams)))
        for i, c in enumerate(cams, 1):
            q, t = colmap_pose(c)
            f.write(struct.pack("<i7di", i, *(list(q) + list(t) + [i])))
            f.write(c["name"].encode("utf-8") + b"\0")
            f.write(struct.pack("<Q", 0))                    # no 2D points
    with open(os.path.join(d, "points3D.bin"), "wb") as f:
        f.write(struct.pack("<Q", len(points)))
        for i, p in enumerate(points, 1):
            rgb = colors[i - 1] if colors else (128, 128, 128)
            f.write(struct.pack("<Q3d3BdQ", i, p[0], p[1], p[2], *([int(v) for v in rgb] + [0.0, 0])))


def write_transforms(out_dir, cams, image_dir="images", ply_name=None):
    """nerfstudio transforms.json: transform_matrix is camera-to-world in OpenGL axes, which are
    Nuke's camera axes, so the Nuke rotation and position go in as they are."""
    frames = []
    for c in cams:
        fx, fy, cx, cy = intrinsics(c)
        m = [[c["r"][i][0], c["r"][i][1], c["r"][i][2], c["t"][i]] for i in range(3)] + [[0, 0, 0, 1]]
        frames.append({"file_path": "%s/%s" % (image_dir, c["name"]), "transform_matrix": m,
                       "fl_x": fx, "fl_y": fy, "cx": cx, "cy": cy,
                       "w": int(c["width"]), "h": int(c["height"])})
    data = {"camera_model": "PINHOLE", "frames": frames}
    if ply_name:
        data["ply_file_path"] = ply_name
    path = os.path.join(out_dir, "transforms.json")
    with open(path, "w") as f:
        json.dump(data, f, indent=1)
    return path


def write_points_ply(path, points, colors=None):
    """ASCII PLY of the tracker points (x y z, uchar rgb), for checking them against the splat.
    Keep it outside a Brush dataset folder: Brush takes any .ply there as the initial splat."""
    with open(path, "w") as f:
        f.write("ply\nformat ascii 1.0\ncomment DBS_SplatTrain tracker points\n"
                "element vertex %d\nproperty float x\nproperty float y\nproperty float z\n"
                "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n" % len(points))
        for i, p in enumerate(points):
            rgb = colors[i] if colors else (128, 128, 128)
            f.write("%.6f %.6f %.6f %d %d %d\n" % (tuple(p) + tuple(int(v) for v in rgb)))
    return path
