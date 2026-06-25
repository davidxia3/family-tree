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


def _stagger(spans, step):
    """Given horizontal bars (y, xa, xb), return adjusted y's so that bars overlapping in x sit at
    DISTINCT heights instead of merging. Narrower bars keep their y; wider overlapping ones are
    pushed up by multiples of `step`."""
    order = sorted(range(len(spans)), key=lambda i: spans[i][2] - spans[i][1])
    adj = [s[0] for s in spans]
    placed = []  # (xa, xb, y)
    for i in order:
        y, xa, xb = spans[i]
        while any(abs(py - y) < step * 0.75 and not (pxb <= xa or pxa >= xb) for pxa, pxb, py in placed):
            y -= step
        adj[i] = y
        placed.append((xa, xb, y))
    return adj


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

    # --- optional grid (behind everything): tile-sized cells. Each generation gets a horizontal at
    # the tile TOP and tile BOTTOM (so the cell is exactly one tile tall); verticals are one tile
    # WIDTH apart (so each cell is one tile wide). Every tile occupies exactly one cell. --grid. ---
    if grid and t:
        any_tile = next(iter(t.values()))
        th, tw = any_tile.height, any_tile.width
        margin = L["margin"]
        gen_gap = th + v_gap
        nrows = max(tile.gen for tile in t.values()) + 1
        for g in range(nrows):
            y0 = margin + g * gen_gap                        # tile top of this generation
            cls = "grid-row" if g % 5 == 0 else "grid"      # emphasise every 5th generation
            out.append(f'<line class="{cls}" x1="0" y1="{_f(y0)}" x2="{_f(W)}" y2="{_f(y0)}"/>')
            out.append(f'<line class="grid" x1="0" y1="{_f(y0 + th)}" x2="{_f(W)}" y2="{_f(y0 + th)}"/>')
            out.append(f'<text class="grid-label" x="3" y="{_f(y0 + 15)}">{g}</text>')
        x, k = margin, 0
        while x <= W:                                       # column verticals, one tile width apart
            out.append(f'<line class="grid" x1="{_f(x)}" y1="0" x2="{_f(x)}" y2="{_f(H)}"/>')
            k += 1
            x = margin + k * tw

    # --- lineage busbars (orthogonal): father down to a SPLIT bar over all children, then
    # vertical drops to each. Bars are collected first so a drop can be broken with a small
    # gap wherever it has to cross another bar (a clean "line hop"). ---
    h_segs = []  # horizontal bars: (y, x_left, x_right)
    v_segs = []  # verticals: (x, y_top, y_bot)  -- parent stems and child drops
    # Rule S: each split bar sits ONE ROW below the parent (drops then run down to the children's
    # real depth). Two parents on the same row whose bars overlap would merge into one bar, so the
    # bars are collected first and overlapping ones are STAGGERED to distinct heights.
    fam = []
    for father, kids in lay.families:
        if father not in t:
            continue
        pf = t[father]
        ks = [t[k] for k in kids if k in t]
        if not ks:
            continue
        p_bottom = pf.top + pf.height
        bus = p_bottom + v_gap / 2.0
        xmin = min(min(k.x for k in ks), pf.x)
        xmax = max(max(k.x for k in ks), pf.x)
        fam.append((bus, xmin, xmax, pf, ks, p_bottom))
    fam_bus = _stagger([(f[0], f[1], f[2]) for f in fam], v_gap / 6.0)
    for (bus0, xmin, xmax, pf, ks, p_bottom), bus in zip(fam, fam_bus):
        h_segs.append((bus, xmin, xmax))
        v_segs.append((pf.x, min(p_bottom, bus), max(p_bottom, bus)))     # parent stem
        for k in ks:
            cy = k.top if k.top >= bus else k.top + k.height   # a same-row child connects at its BOTTOM
            v_segs.append((k.x, min(bus, cy), max(bus, cy)))   # drop to each child

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

    # --- parentless sibling busbars (rule Sib): like a family busbar but with NO parent stem.
    # Default height top - v_gap/4 (clear of the row's parent busbar at top - v_gap/2). Overlapping
    # sibling bars (e.g. the 薄昭-薄后 line nested inside 呂太后's 5-sibling line) are STAGGERED so
    # they don't merge — the narrower one stays low (shorter), wider ones rise. The bars are NOT in
    # h_segs, so a crossing lineage vertical (e.g. 漢太上皇 -> 漢高祖) stays SOLID; the bar hops it. ---
    sib = []
    for grp in lay.sibling_groups:
        gs = [t[m] for m in grp if m in t]
        if len(gs) < 2:
            continue
        top = min(k.top for k in gs)
        xa, xb = min(k.x for k in gs), max(k.x for k in gs)
        sib.append((top - v_gap / 4.0, xa, xb, gs))
    sib_bus = _stagger([(s[0], s[1], s[2]) for s in sib], v_gap / 6.0)
    for (bus0, xa, xb, gs), bus in zip(sib, sib_bus):
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

    # --- married-out daughter connectors (rule MO): a separate line to a daughter who married into
    # another family (she sits beside her husband, off in his part of the chart). It rises from the
    # father's CHILD BUSBAR — an upward extension of the drop to the busbar's nearest child (the one
    # closest to the daughter) — then crosses OVER (hopping any verticals) and down to the daughter. ---
    fam_kids = {f: [t[k] for k in ks if k in t] for f, ks in lay.families}
    for father, daughter in lay.married_out:
        if father not in t or daughter not in t:
            continue
        pf, dt = t[father], t[daughter]
        bus_y = pf.top + pf.height + v_gap / 2.0          # the father's child busbar (rule S)
        ends = [k.x for k in fam_kids.get(father, [])] + [pf.x]
        near_x = max(ends) if dt.x > max(ends) else min(ends)   # busbar end nearest the daughter
        bar = min(pf.top, dt.top) - v_gap * 0.3
        out.append(f'<line class="edge-lineage" x1="{_f(near_x)}" y1="{_f(bar)}" x2="{_f(near_x)}" y2="{_f(bus_y)}"/>')
        xa, xb = sorted((near_x, dt.x))
        cxs = sorted(x for x, ya, yb in v_segs if ya + 1.0 < bar < yb - 1.0 and xa + 1.0 < x < xb - 1.0)
        cur = xa
        for cx in cxs:
            if cx - HOP > cur:
                out.append(f'<line class="edge-lineage" x1="{_f(cur)}" y1="{_f(bar)}" x2="{_f(cx - HOP)}" y2="{_f(bar)}"/>')
            cur = cx + HOP
        if xb > cur:
            out.append(f'<line class="edge-lineage" x1="{_f(cur)}" y1="{_f(bar)}" x2="{_f(xb)}" y2="{_f(bar)}"/>')
        out.append(f'<line class="edge-lineage" x1="{_f(dt.x)}" y1="{_f(bar)}" x2="{_f(dt.x)}" y2="{_f(dt.top)}"/>')

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
