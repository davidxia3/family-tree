"""Renderer: a saved positions.yaml -> SVG string.

All styling lives in a single <style> block in <defs> (CSS classes), so the
background, tiles, lines, and fonts can be restyled without touching the data.
A person's `color` is a key into cfg['colors'] (a fill + text pair).
"""
from __future__ import annotations


def _f(v: float) -> str:
    return f"{v:.1f}"


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _split(a: float, b: float, hops, g: float):
    """Interval [a,b] minus a g-wide gap centred on each hop in range -> list of (start, end)."""
    lo, hi = (a, b) if a <= b else (b, a)
    cuts = sorted((h - g / 2.0, h + g / 2.0) for h in (hops or []) if lo <= h <= hi)
    pieces, cur = [], lo
    for cs, ce in cuts:
        if cs > cur:
            pieces.append((cur, min(cs, hi)))
        cur = max(cur, ce)
    if cur < hi:
        pieces.append((cur, hi))
    return pieces


def _luminance(hexstr: str) -> float:
    """Perceived brightness 0..1 of a #rrggbb color (unparseable -> 1.0 = light)."""
    h = hexstr.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except (ValueError, IndexError):
        return 1.0
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


def _color_pair(key, cfg: dict):
    """Resolve a person's color KEY to (fill, text) from cfg['colors'], or None if unset/unknown.
    A raw '#hex' is honored too (legacy): fill = the hex, text auto-picked by contrast."""
    if not key:
        return None
    S = cfg["style"]
    if isinstance(key, str) and key.startswith("#"):
        return key, (S["text_light"] if _luminance(key) < 0.5 else S["text_color"])
    pair = (cfg.get("colors") or {}).get(key)
    if not pair:
        return None
    return pair.get("fill"), pair.get("text")


def _css(S: dict) -> str:
    return (
        ".bg{fill:%s;}" % S["background"]
        + ".tile{fill:%s;stroke:%s;stroke-width:%s;}" % (S["default_fill"], S["tile_stroke"], S["tile_stroke_width"])
        + ".name{fill:%s;font-family:%s;font-size:%spx;}" % (S["text_color"], S["font_family"], S["font_size"])
        + ".edge-lineage{stroke:%s;stroke-width:%s;fill:none;}" % (S["lineage_stroke"], S["lineage_width"])
    )


def render_positions_svg(entities: dict, cfg: dict, cell: dict | None = None) -> str:
    """Render the FINAL svg straight from a saved positions.yaml — NO layout passes.

    `entities` is the file's `entities` map (absolute editor px); it is fully self-contained:
    each tile carries its own `name` (display text) and `color` (a key into cfg['colors']).
    Tile geometry comes from the file's `cell` block (w/h/pitch). Every segment is drawn as a
    solid line, split into pieces wherever it carries `hops` (a `line_hop_length`-wide gap each).
    """
    S = cfg["style"]
    L = cfg["layout"]
    cb = L["char_box"]                       # vertical pitch between stacked characters
    r = L["tile_radius"]
    margin = L["margin"]
    hop_len = L["line_hop_length"]
    cell = cell or {}
    tw = cell.get("w", L["tile_width"])
    th = cell.get("h", L["tile_height"])
    pitch = cell.get("pitch", th + L["v_gap"])

    tiles = []                               # (id, x_left, y_top, name, color)
    lines = []                               # (is_h, fixed, a, b, hops)
    xs, ys = [], []
    for eid, e in entities.items():
        typ = e.get("type")
        if typ == "tile":
            x, y = float(e["x"]), float(e["row"]) * pitch
            tiles.append((eid, x, y, e.get("name") or eid, e.get("color")))
            xs += [x, x + tw]; ys += [y, y + th]
        elif typ == "hseg":
            y, x1, x2 = float(e["y"]), float(e["x1"]), float(e["x2"])
            lines.append((True, y, x1, x2, e.get("hops") or [])); xs += [x1, x2]; ys.append(y)
        elif typ == "vseg":
            x, y1, y2 = float(e["x"]), float(e["y1"]), float(e["y2"])
            lines.append((False, x, y1, y2, e.get("hops") or [])); xs.append(x); ys += [y1, y2]
    if not xs:
        xs, ys = [0.0], [0.0]
    minx, miny = min(xs), min(ys)
    dx, dy = margin - minx, margin - miny     # shift so the content starts at `margin`
    W = (max(xs) - minx) + 2 * margin
    H = (max(ys) - miny) + 2 * margin

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_f(W)}" height="{_f(H)}" '
        f'viewBox="0 0 {_f(W)} {_f(H)}">',
        "<defs><style>" + _css(S) + "</style></defs>",
        f'<rect class="bg" x="0" y="0" width="{_f(W)}" height="{_f(H)}"/>',
    ]
    for (is_h, fixed, a, b, hops) in lines:   # edges first, under the tiles; split at each hop
        for (s, t) in _split(a, b, hops, hop_len):
            if is_h:
                out.append(f'<line class="edge-lineage" x1="{_f(s + dx)}" y1="{_f(fixed + dy)}" '
                           f'x2="{_f(t + dx)}" y2="{_f(fixed + dy)}"/>')
            else:
                out.append(f'<line class="edge-lineage" x1="{_f(fixed + dx)}" y1="{_f(s + dy)}" '
                           f'x2="{_f(fixed + dx)}" y2="{_f(t + dy)}"/>')
    for (eid, x, y, name, color) in tiles:    # tiles on top
        pair = _color_pair(color, cfg)        # color is a KEY into cfg['colors']
        decl = f' style="fill:{pair[0]}"' if pair else ""
        out.append(f'<rect class="tile" x="{_f(x + dx)}" y="{_f(y + dy)}" width="{_f(tw)}" '
                   f'height="{_f(th)}" rx="{r}" ry="{r}"{decl}/>')
        tstyle = f' style="fill:{pair[1]}"' if pair else ""
        cx, top0 = x + dx + tw / 2.0, y + dy + cb * 0.25     # names TOP-aligned
        for i, ch in enumerate(name):
            out.append(f'<text class="name" x="{_f(cx)}" y="{_f(top0 + i * cb + cb * 0.78)}"'
                       f'{tstyle} text-anchor="middle">{_esc(ch)}</text>')
    out.append("</svg>")
    return "\n".join(out)
