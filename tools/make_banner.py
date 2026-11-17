# DBS_SplatTrain - by David Borrull
# MIT License - Copyright (c) 2026 David Borrull. See LICENSE.
"""Draws the README banner: docs/images/banner.jpg (1600 x 440), in the style of the other DBS
tools' banners (DBS_SceneProjection, ComfyBridge).

python tools/make_banner.py [--image docs/images/banner_source.jpg]   (Pillow; Segoe UI, Windows)

Left: the node icon, large, on a gradient, with the name and two lines of text.
Right: --image (fitted to the height, faded in from the left): the trained splat in Nuke's 3D view.
"""

import argparse
import os
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_icon  # noqa: E402

W, H = 1600, 440
BG = (22, 24, 28)
GLOW = (38, 64, 104)                        # the icon's blue splat, dimmed
FONTS = "C:/Windows/Fonts"
TITLE = "DBS_SplatTrain"
SUB = "Gaussian splats from your camera track, in Nuke"
FEATURES = "trained with Brush  \u00b7  aligned to the track camera  \u00b7  Nuke 17 splat nodes"
TITLE_MAX_W = 640
TITLE_PREFIX = (255, 160, 80)               # the DBS_ prefix, in the icon's orange splat
FADE_W = 220                                # px over which the picture fades in from its left edge


def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), size)


def lerp(a, b, t):
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def background():
    im = Image.new("RGB", (W, H), BG)
    px = im.load()
    for x in range(W):
        t = min(max((x - 60) / 820.0, 0.0), 1.0)
        t = t * t * (3 - 2 * t)
        c = lerp(GLOW, BG, t)
        for y in range(H):
            v = 1.0 - 0.18 * abs(y - H / 2) / (H / 2)
            px[x, y] = tuple(int(ch * v) for ch in c)
    return im


def picture(path):
    src = Image.open(path).convert("RGB")
    s = H / float(src.height)
    src = src.resize((int(src.width * s), H), Image.LANCZOS)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.paste(src, (W - src.width, 0))
    return out


def fade(layer):
    a = layer.getchannel("A")
    x0 = a.getbbox()[0]
    ramp = Image.new("L", (W, H), 0)
    rp = ramp.load()
    for x in range(W):
        t = min(max((x - x0) / float(FADE_W), 0.0), 1.0)
        for y in range(H):
            rp[x, y] = int(255 * t * t * (3 - 2 * t))
    layer.putalpha(ImageChops.multiply(a, ramp))
    return layer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=os.path.join(ROOT, "docs", "images", "banner_source.jpg"))
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "images", "banner.jpg"))
    a = ap.parse_args()

    im = background().convert("RGBA")
    im.alpha_composite(fade(picture(a.image)))

    icon = make_icon.draw(250)
    shadow = Image.new("RGBA", im.size, (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 110), (100, 104, 350, 354), icon.getchannel("A"))
    im.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(14)))
    im.alpha_composite(icon, (95, 95))

    d = ImageDraw.Draw(im)
    prefix, name = TITLE.split("_", 1)
    prefix += "_"
    size = 104
    while size > 40 and font("segoeui.ttf", size).getlength(prefix + name) > TITLE_MAX_W:
        size -= 2
    f = font("segoeui.ttf", size)
    d.text((402, 248), prefix, font=f, fill=TITLE_PREFIX, anchor="ls")
    d.text((402 + f.getlength(prefix), 248), name, font=f, fill=(255, 255, 255), anchor="ls")
    d.text((406, 272), SUB, font=font("segoeuil.ttf", 34), fill=(216, 222, 232))
    d.text((406, 326), FEATURES, font=font("segoeuil.ttf", 22), fill=(152, 162, 178))

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    im.convert("RGB").save(a.out, quality=92, optimize=True)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
