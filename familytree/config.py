"""Layout + style configuration.

Defaults live here; an optional config.yaml at the repo root is deep-merged on
top so you can restyle without touching code. Nothing here affects the
genealogy DATA — only sizes, spacing, colors, fonts, and orientation.
"""
from __future__ import annotations

import copy
from typing import Optional

import yaml

DEFAULTS = {
    # rtl = classical Chinese reading: senior/primary person on the RIGHT.
    # The engine computes everything left-to-right, then mirrors x at the end.
    "orientation": "rtl",
    "layout": {
        "char_box": 36,        # px box per stacked character (square-ish)
        "tile_pad": 9,         # px padding inside a tile
        # ONE standardized horizontal gap (edge-to-edge), used everywhere: between
        # sibling subtrees (the per-row minimum), between husband and wife, and
        # between consecutive wives.
        "h_gap": 30,
        # ONE standardized vertical gap (between a tile's bottom and the next row).
        "v_gap": 60,
        "margin": 70,          # canvas padding
        "tile_radius": 8,      # tile corner radius
    },
    "style": {
        "background": "#f7f3ea",
        "default_fill": "#fffdf7",
        "tile_stroke": "#3a3a3a",
        "tile_stroke_width": 1.5,
        "text_color": "#1a1a1a",
        "text_light": "#f7f3ea",      # text on dark-fill tiles (auto-picked by contrast)
        "font_family": "Songti SC, STSong, Noto Serif CJK SC, PingFang SC, serif",
        "font_size": 30,
        "lineage_stroke": "#5b5b5b",   # solid: parent -> child
        "lineage_width": 1.6,
        "marriage_stroke": "#9a6b4a",  # solid: husband -- wife
        "marriage_width": 1.6,
        "secondary_stroke": "#a23b3b", # dashed: married-in daughter -> father
        "secondary_width": 1.4,
        "secondary_dash": "5 4",
        "highlight_stroke": "#e8462a", # transient outline for newly-added (under-review) tiles
        "highlight_width": 4,
    },
}


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Optional[str] = None) -> dict:
    user = {}
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                user = yaml.safe_load(f) or {}
        except FileNotFoundError:
            user = {}
    return _deep_merge(DEFAULTS, user)
