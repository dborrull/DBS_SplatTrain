# DBS_SplatTrain - by David Borrull
# MIT License - Copyright (c) 2026 David Borrull. See LICENSE.
"""Add still photos of the set to an exported dataset: COLMAP places them in the track's world,
with the track cameras kept exactly as they are (poses and focal).

python tools/DBS_add_photos.py <dataset> <photos folder> [--colmap=bin/colmap-4.2.1/bin/colmap.exe]

<dataset>: what DBS_export_shot.py wrote (images/frame_NNNN.png, sparse/0). Plain Python (Nuke's own
python.exe works: no numpy). Work files go to <dataset>/../colmap. At the end the dataset holds the
frames plus the photos that COLMAP could place (undistorted, pinhole), and the COLMAP points
instead of the tracker's; the track-only model is kept in colmap/track_sparse.

Steps: SIFT features (frames: one pinhole camera with the track's intrinsics; photos: one
SIMPLE_RADIAL camera from their EXIF), all pairs matched, points triangulated from the fixed track
cameras, photos registered with the track frames fixed (a first pass finds the photos' focal, the
second keeps the track's focal fixed), photos undistorted.
"""

import argparse
import glob
import os
import shutil
import sqlite3
import struct
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_COLMAP = os.path.join(ROOT, "bin", "colmap-4.2.1", "bin", "colmap.exe")
PHOTO_EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff")
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class Fail(Exception):
    pass


def run(colmap, log, *args):
    cmd = [colmap] + [str(a) for a in args]
    log.write("\n$ %s\n" % subprocess.list2cmdline(cmd))
    log.flush()
    res = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    if res.returncode != 0:
        raise Fail("COLMAP %s failed (see %s)" % (args[0], log.name))


def read_txt(path):
    return [l.rstrip("\n") for l in open(path) if l.strip() and not l.startswith("#")]


def read_images_txt(path):
    """{name: (qw qx qy qz tx ty tz as floats, camera_id)} from a COLMAP images.txt."""
    out = {}
    lines = [l.rstrip("\n") for l in open(path) if not l.startswith("#")]
    for l in lines[0::2]:
        s = l.split()
        if len(s) >= 10:
            out[s[9]] = ([float(x) for x in s[1:8]], int(s[8]))
    return out


def cameras_txt(path):
    out = {}
    for l in read_txt(path):
        s = l.split()
        out[int(s[0])] = (s[1], int(s[2]), int(s[3]), [float(x) for x in s[4:]])
    return out


def to_txt(colmap, log, model, out):
    os.makedirs(out, exist_ok=True)
    run(colmap, log, "model_converter", "--input_path", model, "--output_path", out, "--output_type", "TXT")


def main():
    sys.stdout.reconfigure(line_buffering=True)      # the node shows each step as it comes
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("photos")
    ap.add_argument("--colmap", default=DEFAULT_COLMAP)
    a = ap.parse_args()
    data, colmap = os.path.abspath(a.dataset), os.path.abspath(a.colmap)
    if not os.path.isfile(colmap):
        raise Fail("COLMAP not found: %s" % colmap)
    sparse = os.path.join(data, "sparse", "0")
    if not os.path.isfile(os.path.join(sparse, "images.bin")):
        raise Fail("No exported dataset in %s" % data)
    photos = sorted(f for f in glob.glob(os.path.join(a.photos, "*")) if f.lower().endswith(PHOTO_EXT))
    if not photos:
        raise Fail("No photos (.jpg .png .tif) in %s" % a.photos)

    work = os.path.join(os.path.dirname(data), "colmap")
    if os.path.isdir(work):
        shutil.rmtree(work)
    img = os.path.join(work, "images")
    os.makedirs(img)
    t0 = time.time()
    log = open(os.path.join(work, "colmap.log"), "w")

    # Track model as text: the frames' poses and intrinsics.
    track_txt = os.path.join(work, "track_txt")
    to_txt(colmap, log, sparse, track_txt)
    track = read_images_txt(os.path.join(track_txt, "images.txt"))
    cams = cameras_txt(os.path.join(track_txt, "cameras.txt"))
    models = {(c[0], c[1], c[2], tuple(round(p, 6) for p in c[3])) for c in cams.values()}
    if len(models) != 1:
        raise Fail("The track cameras do not all share one lens (animated focal?): not supported yet.")
    model, cw, ch, params = next(iter(cams.values()))
    shutil.copytree(sparse, os.path.join(work, "track_sparse"))

    # Images: the frames and the photos (renamed photo_<name>, so they cannot clash with frames).
    frames = sorted(track)
    for f in frames:
        shutil.copy2(os.path.join(data, "images", f), img)
    names = {}
    for p in photos:
        n = "photo_" + os.path.basename(p).replace(" ", "_")
        names[n] = p
        shutil.copy2(p, os.path.join(img, n))
    open(os.path.join(work, "frames.txt"), "w").write("\n".join(frames) + "\n")
    open(os.path.join(work, "photos.txt"), "w").write("\n".join(sorted(names)) + "\n")
    print("DBS: %d frames, %d photos" % (len(frames), len(names)))

    db = os.path.join(work, "database.db")
    run(colmap, log, "feature_extractor", "--database_path", db, "--image_path", img,
        "--image_list_path", os.path.join(work, "frames.txt"), "--ImageReader.camera_model", model,
        "--ImageReader.single_camera", 1, "--ImageReader.camera_params", ",".join(repr(p) for p in params))
    run(colmap, log, "feature_extractor", "--database_path", db, "--image_path", img,
        "--image_list_path", os.path.join(work, "photos.txt"), "--ImageReader.camera_model", "SIMPLE_RADIAL",
        "--ImageReader.single_camera", 1)
    print("DBS: features in %.0f s" % (time.time() - t0))
    run(colmap, log, "exhaustive_matcher", "--database_path", db)
    print("DBS: matched in %.0f s" % (time.time() - t0))

    # The track as a COLMAP model with the database's ids: one camera, one rig, one frame per image.
    con = sqlite3.connect(db)
    ids = {n: (i, c) for i, n, c in con.execute("select image_id, name, camera_id from images")}
    frame_of = {d: f for f, d in con.execute("select frame_id, data_id from frame_data")}
    rig_of = {f: r for f, r in con.execute("select frame_id, rig_id from frames")}
    fixed = os.path.join(work, "track_fixed")
    os.makedirs(fixed)
    cam_id = ids[frames[0]][1]
    rig_id = rig_of[frame_of[ids[frames[0]][0]]]
    with open(os.path.join(fixed, "cameras.txt"), "w") as f:
        f.write("%d %s %d %d %s\n" % (cam_id, model, cw, ch, " ".join(repr(p) for p in params)))
    with open(os.path.join(fixed, "rigs.txt"), "w") as f:
        f.write("%d 1 CAMERA %d\n" % (rig_id, cam_id))
    with open(os.path.join(fixed, "frames.txt"), "w") as ff, open(os.path.join(fixed, "images.txt"), "w") as fi:
        for n in frames:
            iid = ids[n][0]
            q = " ".join(repr(v) for v in track[n][0])
            fi.write("%d %s %d %s\n\n" % (iid, q, cam_id, n))
            ff.write("%d %d %s 1 CAMERA %d %d\n" % (frame_of[iid], rig_id, q, cam_id, iid))
    open(os.path.join(fixed, "points3D.txt"), "w").close()

    tri, reg1, reg2 = (os.path.join(work, d) for d in ("tri", "reg1", "reg2"))
    for d in (tri, reg1, reg2):
        os.makedirs(d)
    run(colmap, log, "point_triangulator", "--database_path", db, "--image_path", img, "--input_path", fixed,
        "--output_path", tri, "--refine_intrinsics", 0, "--Mapper.ba_refine_focal_length", 0,
        "--Mapper.ba_refine_extra_params", 0)
    print("DBS: points triangulated in %.0f s" % (time.time() - t0))

    # Pass 1 finds the photos' focal (it would also nudge the track's: that result is not used).
    common = ["--database_path", db, "--image_path", img, "--input_path", tri, "--Mapper.fix_existing_frames", 1,
              "--Mapper.ba_refine_principal_point", 0, "--Mapper.multiple_models", 0]
    run(colmap, log, "mapper", *(common + ["--output_path", reg1]))
    reg1_txt = os.path.join(work, "reg1_txt")
    to_txt(colmap, log, reg1, reg1_txt)
    photo_cam = ids[sorted(names)[0]][1]
    found = cameras_txt(os.path.join(reg1_txt, "cameras.txt")).get(photo_cam)
    if found is None or not any(n in read_images_txt(os.path.join(reg1_txt, "images.txt")) for n in names):
        raise Fail("COLMAP could not place any photo: they share too little with the shot's frames.")
    con.execute("update cameras set params=?, prior_focal_length=1 where camera_id=?",
                (struct.pack("<%dd" % len(found[3]), *found[3]), photo_cam))
    con.commit()
    con.close()

    # Pass 2: the track's focal stays exactly as it is.
    run(colmap, log, "mapper", *(common + ["--output_path", reg2, "--Mapper.ba_refine_focal_length", 0,
                                           "--Mapper.ba_refine_extra_params", 0]))
    reg2_txt = os.path.join(work, "reg2_txt")
    to_txt(colmap, log, reg2, reg2_txt)
    result = read_images_txt(os.path.join(reg2_txt, "images.txt"))
    for n in frames:
        if n not in result or max(abs(x - y) for x, y in zip(result[n][0], track[n][0])) > 1e-6:
            raise Fail("COLMAP moved the track camera of %s: not using the result." % n)
    if max(abs(x - y) for x, y in zip(cameras_txt(os.path.join(reg2_txt, "cameras.txt"))[cam_id][3], params)) > 1e-6:
        raise Fail("COLMAP changed the track's focal: not using the result.")
    placed = sorted(n for n in names if n in result)
    print("DBS: registered in %.0f s" % (time.time() - t0))

    # Undistort (the frames are pinhole already and come out the same) and write the dataset.
    und = os.path.join(work, "undistorted")
    run(colmap, log, "image_undistorter", "--image_path", img, "--input_path", reg2, "--output_path", und,
        "--output_type", "COLMAP")
    for n in placed:
        shutil.copy2(os.path.join(und, "images", n), os.path.join(data, "images", n))
    for f in os.listdir(sparse):
        os.remove(os.path.join(sparse, f))
    for f in ("cameras.bin", "images.bin", "points3D.bin"):
        shutil.copy2(os.path.join(und, "sparse", f), os.path.join(sparse, f))
    shutil.rmtree(os.path.join(und, "images"))
    print("DBS: photos placed: %d of %d in %.1f min" % (len(placed), len(names), (time.time() - t0) / 60.0))
    left = sorted(set(names) - set(placed))
    if left:
        print("DBS: not placed (too little in common with the shot): " + ", ".join(os.path.basename(names[n]) for n in left))


if __name__ == "__main__":
    try:
        main()
    except Fail as e:
        print("DBS: " + str(e))
        sys.exit(1)
