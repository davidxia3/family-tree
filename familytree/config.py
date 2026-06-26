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
    # fill / text colour PAIRS. `tile` = the default tile (light fill + dark text);
    # `inverse` = used when a tile's fill is dark — its text is picked for contrast,
    # its fill is the reference dark. _derive() copies these into the flat style keys.
    "colors": {
        "tile": {"fill": "#fffdf7", "text": "#1a1a1a"},
        "inverse": {"fill": "#1a1a1a", "text": "#f7f3ea"},
    },
    "layout": {
        # --- the three tile PRIMITIVES; every other geometry value derives from these
        # in _derive(): h_gap = tile_width, v_gap = 2*tile_width, char_box = font_size*1.2.
        # (font_size is the third primitive; it lives under `style`.) ---
        "tile_width": 64,      # px tile width (also the standardized min horizontal gap)
        "tile_height": 308,    # px tile height (fixed; must fit the longest stacked name)
        "line_width": 1.6,     # px stroke of lineage / marriage lines
        "border_width": 1.5,   # px stroke of a tile border
        "line_hop_length": 10, # px gap a line-hop cuts out where one line crosses another
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


def _derive(cfg: dict) -> dict:
    """Compute the geometry that is *derived* from the tile primitives + font size, so
    layout/render/editor all read one consistent set of values. Change only tile_width,
    tile_height (layout) and font_size (style); these follow."""
    L, S = cfg["layout"], cfg["style"]
    w = L["tile_width"]
    L["h_gap"] = w                               # min horizontal distance == one tile width
    L["v_gap"] = 2 * w                           # non-tile (gap) row height == two tile widths
    L["char_box"] = round(S["font_size"] * 1.2)  # vertical pitch between stacked characters
    S["lineage_width"] = S["marriage_width"] = L["line_width"]   # one line width everywhere
    S["marriage_stroke"] = S["lineage_stroke"]   # marriages drawn the same color as lineage lines
    S["tile_stroke_width"] = L["border_width"]
    C = cfg.get("colors") or {}                  # (fill, text) colour pairs -> flat style keys
    if C.get("tile"):
        S["default_fill"], S["text_color"] = C["tile"]["fill"], C["tile"]["text"]
    if C.get("inverse"):
        S["text_light"] = C["inverse"]["text"]   # text on dark per-person fills (its fill is the reference dark)
    return cfg


def load_config(path: Optional[str] = None) -> dict:
    user = {}
    if path:
        try:
            with open(path, encoding="utf-8") as f:
                user = yaml.safe_load(f) or {}
        except FileNotFoundError:
            user = {}
    return _derive(_deep_merge(DEFAULTS, user))
