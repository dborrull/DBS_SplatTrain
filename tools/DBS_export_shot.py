# DBS_SplatTrain - by David Borrull
# MIT License - Copyright (c) 2026 David Borrull. See LICENSE.
"""Export a tracked shot from a Nuke script as a Brush dataset (Nuke terminal, Non-commercial OK).

"C:/Program Files/Nuke17.1v1/Nuke17.1.exe" --nc -t tools/DBS_export_shot.py <script.nk> <read>
    <camera> <out_dir> [--points=CameraTrackerPointCloud1] [--mask=Roto1] [--first=F] [--last=L]
    [--step=N] [--format=colmap|nerfstudio]   (always '=': Nuke eats loose numbers as a frame range)

<read>: the plate node (undistorted: the dataset cameras are pinhole). <camera>: the tracked camera
(e.g. from CameraTracker 'Create Camera'). --points: the tracker's point cloud (initial splats).
--mask: a node whose alpha is 1 on what moves; written to masks/ inverted (black = ignored by
Brush). Frames first..last every step (default: the read's range, every frame).

Writes out_dir/images/frame_NNNN.png (sRGB), out_dir/masks/..., the cameras (COLMAP binary in
sparse/0, or transforms.json) and out_dir/../<name>_points.ply to compare in Nuke.
Non-pixel-aspect plates (e.g. 1280x1080 at 1.5) are stretched to square pixels (1920x1080).
Non-commercial allows about 10 Python Node objects per session: this uses at most 9.
"""

import argparse
import os
import sys
import time

import nuke

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nuke"))
from dbs_splattrain import colour, dataset  # noqa: E402


def rigid(wm):
    r = [[wm[4 * i + j] for j in range(3)] for i in range(3)]
    for j in range(3):                       # remove per-axis scale from the columns
        n = sum(r[i][j] ** 2 for i in range(3)) ** 0.5 or 1.0
        for i in range(3):
            r[i][j] /= n
    return r, [wm[3], wm[7], wm[11]]


def camera_at(cam, frame, name, w, h):
    r, t = rigid([cam["world_matrix"].getValueAt(frame, i) for i in range(16)])
    return {"name": name, "r": r, "t": t, "focal": cam["focal"].valueAt(frame),
            "haperture": cam["haperture"].valueAt(frame),
            "win_translate": [cam["win_translate"].valueAt(frame, 0), cam["win_translate"].valueAt(frame, 1)],
            "width": w, "height": h}


def tracker_points(src):
    pts = []
    for obj in src["geo_select"].getGeometry():
        m = obj.transform()
        for p in obj.points():
            q = m.transform(p)
            pts.append((q.x, q.y, q.z))
    return pts


# Mask: alpha inverted (black = ignored by Brush) plus under 1 % of noise. Brush v0.3.0 fails the
# whole load on any image file under 16 KB ("early eof"), and a flat black-and-white PNG is that
# small; the noise keeps it bigger. Brush v0.3.0 does not read TIFF.
MASK_EXPR = "clamp((1-a)*0.99+random(x,y,0)*0.01)"


def render(src, path, frames, expr=None, square=None):
    """square: (width, height) to stretch a non-square-pixel plate to (Brush needs square pixels)."""
    node = src
    if expr is not None:                     # mask alpha -> rgb, inverted (black = ignored)
        node = nuke.nodes.Expression(expr0=expr, expr1=expr, expr2=expr)
        node.setInput(0, src)
    if square is not None:
        ref = nuke.nodes.Reformat(type="to box", box_fixed=True, box_width=square[0],
                                  box_height=square[1], resize="distort", black_outside=False)
        ref.setInput(0, node)
        node = ref
    w = nuke.nodes.Write(file=path.replace("\\", "/"), file_type="png", channels="rgb")
    if expr is not None and "raw" in w.knobs():
        w["raw"].setValue(True)              # mask values as they are, no colour transform
    else:
        # The same sRGB the node's DBS_FromSRGB undoes on the rendered splat (name per OCIO config).
        name = colour.pick_srgb(w["colorspace"].values())
        if name is None:
            sys.exit("DBS: no sRGB colour space in this OCIO config")
        w["colorspace"].setValue(name)
    print("DBS: Write colorspace:", w["colorspace"].value())
    w.setInput(0, node)
    t0 = time.time()
    nuke.executeMultiple([w], [(frames[0], frames[-1], frames[1] - frames[0] if len(frames) > 1 else 1)])
    return time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    for k in ("script", "read", "camera", "out_dir"):
        ap.add_argument(k)
    ap.add_argument("--points")
    ap.add_argument("--mask")
    ap.add_argument("--first", type=int)
    ap.add_argument("--last", type=int)
    ap.add_argument("--step", type=int, default=1)
    ap.add_argument("--format", choices=("colmap", "nerfstudio"), default="colmap")
    a = ap.parse_args(sys.argv[1:])

    nuke.scriptOpen(a.script)
    read, cam = nuke.toNode(a.read), nuke.toNode(a.camera)
    if read is None or cam is None:
        sys.exit("DBS: node not found: %s" % (a.read if read is None else a.camera))
    first = a.first if a.first is not None else int(read.firstFrame())
    last = a.last if a.last is not None else int(read.lastFrame())
    frames = list(range(first, last + 1, max(1, a.step)))
    w, h = read.width(), read.height()
    pa = read.pixelAspect()
    square = None
    if abs(pa - 1.0) > 1e-3:                 # e.g. DVCPRO HD 1280x1080 at 1.5 -> 1920x1080
        w = int(round(w * pa))
        square = (w, h)
        print("DBS: pixel aspect %.3g: images stretched to %dx%d square pixels" % (pa, w, h))
    out = os.path.abspath(a.out_dir)
    for sub in ("images", "masks") if a.mask else ("images",):
        if not os.path.isdir(os.path.join(out, sub)):
            os.makedirs(os.path.join(out, sub))
    print("DBS: %d frames (%d-%d step %d), %dx%d -> %s" % (len(frames), first, last, a.step, w, h, out))

    sec = render(read, os.path.join(out, "images", "frame_####.png"), frames, square=square)
    print("DBS: images rendered in %.1f s" % sec)
    if a.mask:
        sec = render(nuke.toNode(a.mask), os.path.join(out, "masks", "frame_####.png"), frames, expr=MASK_EXPR,
                     square=square)
        print("DBS: masks rendered in %.1f s" % sec)

    cams = [camera_at(cam, f, "frame_%04d.png" % f, w, h) for f in frames]
    pts = tracker_points(nuke.toNode(a.points)) if a.points else []
    print("DBS: %d cameras, %d tracker points" % (len(cams), len(pts)))
    if a.format == "colmap":
        print("DBS: wrote", dataset.write_colmap(out, cams, pts))
    else:
        print("DBS: wrote", dataset.write_transforms(out, cams))
    if pts:
        ply = os.path.join(os.path.dirname(out), os.path.basename(out) + "_points.ply")
        print("DBS: wrote", dataset.write_points_ply(ply, pts))


main()
