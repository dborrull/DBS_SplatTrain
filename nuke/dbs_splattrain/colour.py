# DBS_SplatTrain - by David Borrull
# MIT License - Copyright (c) 2026 David Borrull. See LICENSE.
"""OCIO colour space names (no Nuke dependency).

Brush learns from sRGB-encoded PNGs, so its splat colours are sRGB too: the plate is written
through sRGB and the rendered splat comes back through it in reverse. Both use the OCIO role
`texture_paint`, which is sRGB in Nuke's default config ("sRGB") and in Nuke's ACES configs
("sRGB Encoded Rec.709 (sRGB)"). Python's PyOpenColorIO does not see Nuke's config, so a
Write's colorspace knob is the reliable list of names."""

SRGB_ROLE = "texture_paint"
SRGB_CANDIDATES = [SRGB_ROLE, "sRGB Encoded Rec.709 (sRGB)", "sRGB - Texture", "srgb_tx", "sRGB"]
SCENE_LINEAR = "scene_linear"          # an OCIO role: present in every config


def knob_names(values):
    """Entries of a colorspace knob's values() ('name<TAB>family<TAB><TAB>alias,alias') ->
    {lowercase name or alias: name}."""
    out = {}
    for v in values:
        parts = v.split("\t")
        name = parts[0].strip()
        if not name:
            continue
        out[name.lower()] = name
        if len(parts) > 3:
            for a in parts[3].split(","):
                if a.strip():
                    out.setdefault(a.strip().lower(), name)
    return out


def pick_srgb(values):
    """The sRGB colour space to write with, from a colorspace knob's values(), or None."""
    names = knob_names(values)
    for c in SRGB_CANDIDATES:
        if c.lower() in names:
            return names[c.lower()]
    return None
