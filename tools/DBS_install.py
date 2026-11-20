# DBS_SplatTrain - by David Borrull
# MIT License - Copyright (c) 2026 David Borrull. See LICENSE.
"""Install / uninstall DBS_SplatTrain for Nuke. install.bat and uninstall.bat run this with Nuke's
own python.exe (plain Python, nothing to install).

python tools/DBS_install.py install   [--yes] [--no-download] [--nuke-dir=DIR]
python tools/DBS_install.py uninstall [--nuke-dir=DIR]

install: adds three lines to menu.py in your .nuke folder (a copy of the old one is kept as
menu.py.bak_DBS_SplatTrain), between two marker comments so uninstall finds them; never twice.
Then offers to download Brush v0.3.0 (needed) and COLMAP 4.2.1 (optional, for set photos) into
bin/, if they are not there yet.
uninstall: removes only the lines between the markers. bin/ (Brush, COLMAP) stays.
"""

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin")
NUKE_DIR = os.path.join(ROOT, "nuke").replace("\\", "/")
START = "# DBS_SplatTrain: added by install.bat (uninstall.bat removes it)"
END = "# end DBS_SplatTrain"
BRUSH = {
    "name": "Brush v0.3.0",
    "url": "https://github.com/ArthurBrussee/brush/releases/download/v0.3.0/brush-app-x86_64-pc-windows-msvc.zip",
    "dir": os.path.join(BIN, "brush-v0.3.0"),
    "exe": os.path.join(BIN, "brush-v0.3.0", "brush_app.exe"),
}
COLMAP_URL = "https://github.com/colmap/colmap/releases/download/4.2.1/colmap-x64-windows-%s.zip"
COLMAP = {
    "name": "COLMAP 4.2.1",
    "dir": os.path.join(BIN, "colmap-4.2.1"),
    "exe": os.path.join(BIN, "colmap-4.2.1", "bin", "colmap.exe"),
}


def nuke_home(arg):
    """The folder Nuke reads menu.py from: ~/.nuke (on Windows, HOME if set, else the user folder)."""
    if arg:
        return os.path.abspath(arg)
    home = os.environ.get("HOME") or os.path.expanduser("~")
    return os.path.join(home, ".nuke")


def block():
    return "\n".join([START,
                      'nuke.pluginAddPath("%s")' % NUKE_DIR,
                      "import DBS_SplatTrain",
                      "DBS_SplatTrain.install_menu()",
                      END]) + "\n"


def split_block(text):
    """(text before, our block, text after); block None if the markers are not there."""
    i = text.find(START)
    if i < 0:
        return text, None, ""
    j = text.find(END, i)
    if j < 0:
        return text, None, ""
    j = text.find("\n", j)
    j = len(text) if j < 0 else j + 1
    return text[:i], text[i:j], text[j:]


def by_hand(text):
    """Lines that load DBS_SplatTrain outside our markers (added by hand, as the README says)."""
    return [l for l in text.splitlines() if "pluginAddPath" in l and "DBS_SplatTrain" in l]


def write_menu(menu, text):
    if os.path.isfile(menu):
        shutil.copy2(menu, menu + ".bak_DBS_SplatTrain")
    with open(menu, "w", newline="\n") as f:
        f.write(text)


def install_menu(nuke_dir):
    menu = os.path.join(nuke_dir, "menu.py")
    text = open(menu).read() if os.path.isfile(menu) else ""
    before, ours, after = split_block(text)
    if ours is not None:
        if ours == block():
            print("DBS: menu.py already loads DBS_SplatTrain from this folder: nothing to change.")
            return True
        write_menu(menu, before + block() + after)
        print("DBS: menu.py pointed DBS_SplatTrain at another folder: now at %s" % NUKE_DIR)
        return True
    hand = by_hand(text)
    if hand:
        print("DBS: menu.py already loads DBS_SplatTrain (added by hand), left as it is:")
        for l in hand:
            print("       " + l.strip())
        if not any(NUKE_DIR.lower() in l.replace("\\", "/").lower() for l in hand):
            print("     That is not this folder (%s): change the path there if you moved it." % NUKE_DIR)
        return True
    os.makedirs(nuke_dir, exist_ok=True)
    if text and not text.endswith("\n"):
        text += "\n"
    write_menu(menu, text + ("\n" if text else "") + block())
    print("DBS: added DBS_SplatTrain to %s" % menu)
    if text:
        print("     (the old one is kept as menu.py.bak_DBS_SplatTrain)")
    return True


def uninstall_menu(nuke_dir):
    menu = os.path.join(nuke_dir, "menu.py")
    if not os.path.isfile(menu):
        print("DBS: no menu.py in %s: nothing to remove." % nuke_dir)
        return
    text = open(menu).read()
    before, ours, after = split_block(text)
    if ours is not None:
        if before.endswith("\n\n"):
            before = before[:-1]
        write_menu(menu, before + after)
        print("DBS: removed DBS_SplatTrain from %s (the old one is kept as menu.py.bak_DBS_SplatTrain)" % menu)
    hand = by_hand(before + after)
    if hand:
        print("DBS: these lines were added by hand, so they are left in menu.py; delete them yourself")
        print("     (with the import DBS_SplatTrain and install_menu() lines after them):")
        for l in hand:
            print("       " + l.strip())
    elif ours is None:
        print("DBS: menu.py does not load DBS_SplatTrain: nothing to remove.")


def ask(question, default, yes):
    if yes:
        return True
    hint = "[Y/n]" if default else "[y/N]"
    try:
        a = input("%s %s " % (question, hint)).strip().lower()
    except EOFError:
        return default
    return default if not a else a.startswith(("y", "s"))


def download(url, path):
    with urllib.request.urlopen(url) as r, open(path, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done, shown = 0, -10
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            pct = 100 * done // total if total else 0
            if pct >= shown + 10:
                shown = pct - pct % 10
                print("     %3d %%  (%d of %d MB)" % (pct, done // 1000000, total // 1000000))


def fetch(tool, url):
    """Download the zip and unzip it into tool['dir'] (one top folder in the zip is dropped)."""
    os.makedirs(BIN, exist_ok=True)
    zpath = os.path.join(BIN, "_download.zip")
    tmp = os.path.join(BIN, "_unzip")
    for p in (zpath, tmp):
        if os.path.isdir(p):
            shutil.rmtree(p)
        elif os.path.isfile(p):
            os.remove(p)
    print("DBS: downloading %s from %s" % (tool["name"], url))
    try:
        download(url, zpath)
        print("DBS: unzipping...")
        with zipfile.ZipFile(zpath) as z:
            z.extractall(tmp)
        src = tmp
        items = os.listdir(tmp)
        if len(items) == 1 and os.path.isdir(os.path.join(tmp, items[0])):
            src = os.path.join(tmp, items[0])
        if os.path.isdir(tool["dir"]):
            shutil.rmtree(tool["dir"])
        shutil.move(src, tool["dir"])
    finally:
        for p in (zpath, tmp):
            if os.path.isdir(p):
                shutil.rmtree(p)
            elif os.path.isfile(p):
                os.remove(p)
    if not os.path.isfile(tool["exe"]):
        raise RuntimeError("%s was unzipped but %s is not there" % (tool["name"], tool["exe"]))
    print("DBS: %s ready: %s" % (tool["name"], tool["exe"]))


def has_nvidia():
    try:
        return subprocess.run(["nvidia-smi"], capture_output=True).returncode == 0
    except OSError:
        return False


def install_tools(yes):
    if os.path.isfile(BRUSH["exe"]):
        print("DBS: Brush is there: %s" % BRUSH["exe"])
    elif ask("Download Brush v0.3.0 (159 MB, needed to train)?", True, yes):
        fetch(BRUSH, BRUSH["url"])
    else:
        print("DBS: no Brush: set its path in the node's Settings tab (brush) before training.")

    if os.path.isfile(COLMAP["exe"]):
        print("DBS: COLMAP is there: %s" % COLMAP["exe"])
        return
    kind = "cuda" if has_nvidia() else "nocuda"
    size = {"cuda": 415, "nocuda": 128}[kind]
    if ask("Download COLMAP 4.2.1 (%d MB, %s; only needed for set photos)?" % (size, kind), False, False):
        fetch(COLMAP, COLMAP_URL % kind)
    else:
        print("DBS: no COLMAP (only needed for set photos; run install.bat again to get it later).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["install", "uninstall"])
    ap.add_argument("--yes", action="store_true", help="download Brush without asking")
    ap.add_argument("--no-download", action="store_true", help="only menu.py")
    ap.add_argument("--nuke-dir", default="", help="the .nuke folder (default: ~/.nuke)")
    a = ap.parse_args()
    nuke_dir = nuke_home(a.nuke_dir)
    print("DBS_SplatTrain in %s" % ROOT)
    print(".nuke folder: %s" % nuke_dir)
    print()
    if a.action == "uninstall":
        uninstall_menu(nuke_dir)
        print()
        print("DBS: Brush and COLMAP stay in %s: delete the folder to remove everything." % ROOT)
        return
    install_menu(nuke_dir)
    if not a.no_download:
        print()
        install_tools(a.yes)
    print()
    print("DBS: done. Restart Nuke: the node is in the Nodes toolbar under DBS > DBS_SplatTrain.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nDBS: stopped.")
        sys.exit(1)
    except Exception as e:
        print("DBS: error: %s" % e)
        sys.exit(1)
