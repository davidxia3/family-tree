"""Renderer: LayoutResult -> SVG string.

All styling lives in a single <style> block in <defs> (CSS classes), so the
background, tiles, lines, and fonts can be restyled later without touching
layout. A person's `color` (if set) overrides only that tile's fill.
"""
from __future__ import annotations

from .layout import LayoutResult


def _f(v: float) -> str:
    return f"{v:.1f}"


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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


def _css(S: dict) -> str:
    return (
        ".bg{fill:%s;}" % S["background"]
        + ".tile{fill:%s;stroke:%s;stroke-width:%s;}" % (S["default_fill"], S["tile_stroke"], S["tile_stroke_width"])
        + ".name{fill:%s;font-family:%s;font-size:%spx;}" % (S["text_color"], S["font_family"], S["font_size"])
        + ".edge-lineage{stroke:%s;stroke-width:%s;fill:none;}" % (S["lineage_stroke"], S["lineage_width"])
        + ".edge-marriage{stroke:%s;stroke-width:%s;fill:none;}" % (S["marriage_stroke"], S["marriage_width"])
        + ".grid{stroke:#cfc8b8;stroke-width:0.6;}.grid-row{stroke:#bcae90;stroke-width:0.8;}"
        + ".grid-label{fill:#a99c7e;font-family:%s;font-size:13px;}" % S["font_family"]
    )


def render_svg(lay: LayoutResult, cfg: dict, highlight=None, grid=False) -> str:
    S = cfg["style"]
    L = cfg["layout"]
    v_gap = L["v_gap"]
    highlight = set(highlight or ())
    W, H = lay.width, lay.height
    t = lay.tiles
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_f(W)}" height="{_f(H)}" '
        f'viewBox="0 0 {_f(W)} {_f(H)}">',
        "<defs><style>" + _css(S) + "</style></defs>",
        f'<rect class="bg" x="0" y="0" width="{_f(W)}" height="{_f(H)}"/>',
    ]

    # --- optional verification grid (behind everything): a horizontal line + number at each
    # generation row, and faint verticals one TILE-WIDTH apart. Toggled with --grid. ---
    if grid and t:
        any_tile = next(iter(t.values()))
        th, tw = any_tile.height, any_tile.width
        margin = L["margin"]
        gen_gap = th + v_gap
        col_step = tw                                       # vertical-line pitch = one tile width
        nrows = max(tile.gen for tile in t.values()) + 1
        for g in range(nrows + 1):
            y = margin + g * gen_gap
            cls = "grid-row" if g % 5 == 0 else "grid"     # emphasise every 5th row
            out.append(f'<line class="{cls}" x1="0" y1="{_f(y)}" x2="{_f(W)}" y2="{_f(y)}"/>')
            if g < nrows:
                out.append(f'<text class="grid-label" x="3" y="{_f(y + 15)}">{g}</text>')
        x, k = margin, 0
        while x <= W:
            out.append(f'<line class="grid" x1="{_f(x)}" y1="0" x2="{_f(x)}" y2="{_f(H)}"/>')
            k += 1
            x = margin + k * col_step

    # --- lineage busbars (orthogonal): father down to a SPLIT bar over all children, then
    # vertical drops to each. Bars are collected first so a drop can be broken with a small
    # gap wherever it has to cross another bar (a clean "line hop"). ---
    h_segs = []  # horizontal bars: (y, x_left, x_right)
    v_segs = []  # verticals: (x, y_top, y_bot)  -- parent stems and child drops
    for father, kids in lay.families:
        if father not in t:
            continue
        pf = t[father]
        ks = [t[k] for k in kids if k in t]
        if not ks:
            continue
        p_bottom = pf.top + pf.height
        # Rule S: the split bar sits ONE ROW below the parent — at the height it would have if the
        # children were direct children one tile down — regardless of how far the actual (possibly
        # descendant) children render. The drops then extend down to each child's real depth. (For
        # ordinary children one row below this is unchanged; for long descendant-of lines, e.g.
        # 劉累 → 漢/劉賈 or 大廉 → 孟戲/中衍, the bar stays high and the drops run long.)
        bus = p_bottom + v_gap / 2.0
        xmin = min(min(k.x for k in ks), pf.x)
        xmax = max(max(k.x for k in ks), pf.x)
        h_segs.append((bus, xmin, xmax))
        v_segs.append((pf.x, p_bottom, bus))              # parent stem
        for k in ks:
            v_segs.append((k.x, bus, k.top))              # drop to each child

    for y, xa, xb in h_segs:
        out.append(f'<line class="edge-lineage" x1="{_f(xa)}" y1="{_f(y)}" x2="{_f(xb)}" y2="{_f(y)}"/>')

    HOP = 4.0  # half-gap a vertical leaves where it crosses a bar
    for x, ya, yb in v_segs:
        crossings = sorted(hy for hy, hxa, hxb in h_segs
                           if ya + 1.0 < hy < yb - 1.0 and hxa + 1.0 < x < hxb - 1.0)
        cur = ya
        for cy in crossings:
            if cy - HOP > cur:
                out.append(f'<line class="edge-lineage" x1="{_f(x)}" y1="{_f(cur)}" x2="{_f(x)}" y2="{_f(cy - HOP)}"/>')
            cur = cy + HOP
        if yb > cur:
            out.append(f'<line class="edge-lineage" x1="{_f(x)}" y1="{_f(cur)}" x2="{_f(x)}" y2="{_f(yb)}"/>')

    # --- parentless sibling busbars (rule Sib): like a family busbar but with NO parent stem
    # (no vertical rising from the bar's middle). The bar is NOT added to h_segs, so a crossing
    # lineage vertical (e.g. 漢太上皇 -> 漢高祖) stays SOLID; instead THIS bar hops over it. ---
    for grp in lay.sibling_groups:
        gs = [t[m] for m in grp if m in t]
        if len(gs) < 2:
            continue
        top = min(k.top for k in gs)
        # A parent one row up would put the bar at top - v_gap/2 — but that is exactly the row's
        # PARENT busbar height, so it would coincide with it and only touch the crossed drop at
        # its endpoint. Drop the sibling bar to top - v_gap/4 so it sits clear of the parent bar
        # and crosses any straddled lineage drop in that drop's interior (a clean hop).
        bus = top - v_gap / 4.0
        xa, xb = min(k.x for k in gs), max(k.x for k in gs)
        # horizontal bar, broken where a (solid) lineage vertical crosses it
        cxs = sorted(x for x, ya, yb in v_segs if ya + 1.0 < bus < yb - 1.0 and xa + 1.0 < x < xb - 1.0)
        cur = xa
        for cx in cxs:
            if cx - HOP > cur:
                out.append(f'<line class="edge-lineage" x1="{_f(cur)}" y1="{_f(bus)}" x2="{_f(cx - HOP)}" y2="{_f(bus)}"/>')
            cur = cx + HOP
        if xb > cur:
            out.append(f'<line class="edge-lineage" x1="{_f(cur)}" y1="{_f(bus)}" x2="{_f(xb)}" y2="{_f(bus)}"/>')
        for k in gs:                            # drop from the bar to each sibling
            out.append(f'<line class="edge-lineage" x1="{_f(k.x)}" y1="{_f(bus)}" x2="{_f(k.x)}" y2="{_f(k.top)}"/>')

    # --- marriage ties (husband -- wife), connecting facing edges ---
    for a, b in lay.marriages:
        ta, tb = t[a], t[b]
        y = ta.top + min(ta.height, tb.height) / 2.0
        if tb.x < ta.x:
            x1, x2 = tb.x + tb.width / 2, ta.x - ta.width / 2
        else:
            x1, x2 = ta.x + ta.width / 2, tb.x - tb.width / 2
        out.append(f'<line class="edge-marriage" x1="{_f(x1)}" y1="{_f(y)}" x2="{_f(x2)}" y2="{_f(y)}"/>')

    # (no dashed/secondary edges — every relationship is a solid orthogonal line)

    # --- tiles (drawn last, on top of the edges) ---
    cb = L["char_box"]
    pad = L["tile_pad"]
    r = L["tile_radius"]
    for tile in lay.tiles.values():
        x = tile.x - tile.width / 2
        # Per-person color (and the transient new-batch highlight) go in an inline
        # STYLE, not presentation attributes: a CSS class rule (.tile{...}) outranks a
        # presentation attribute in browsers (though librsvg honors either).
        decl = []
        if tile.color:
            decl.append(f"fill:{tile.color}")
        if tile.id in highlight:
            decl.append(f"stroke:{S['highlight_stroke']}")
            decl.append(f"stroke-width:{S['highlight_width']}")
        style = f' style="{";".join(decl)}"' if decl else ""
        out.append(
            f'<rect class="tile" x="{_f(x)}" y="{_f(tile.top)}" width="{_f(tile.width)}" '
            f'height="{_f(tile.height)}" rx="{r}" ry="{r}"{style}/>'
        )
        # names are TOP-aligned; any extra space trails at the bottom of the tile.
        # On a dark fill, switch to light text for contrast (inline style wins over .name).
        tstyle = ""
        if tile.color and _luminance(tile.color) < 0.5:
            tstyle = f' style="fill:{S["text_light"]}"'
        for i, ch in enumerate(tile.name):
            cy = tile.top + pad + i * cb + cb * 0.78
            out.append(f'<text class="name" x="{_f(tile.x)}" y="{_f(cy)}"{tstyle} text-anchor="middle">{_esc(ch)}</text>')

    out.append("</svg>")
    return "\n".join(out)
