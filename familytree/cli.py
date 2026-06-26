"""Command-line interface:  python -m familytree <command>

  edit      positions.yaml -> build/editor.html   (the semi-manual editor)
  render    positions.yaml -> build/family_tree.svg + integrity checks

positions.yaml is the single, self-contained data file: each tile carries its own
name + color, plus the lines you draw. There is no separate genealogy database.
"""
from __future__ import annotations

import argparse
import os
import subprocess
from shutil import which

import yaml

from .config import load_config

DEFAULT_CONFIG = "config.yaml"
DEFAULT_SVG = "build/family_tree.svg"
DEFAULT_POSITIONS = "positions.yaml"


def _cfg(args) -> dict:
    return load_config(args.config if os.path.exists(args.config) else None)


def _load_positions(path):
    """Return (entities, cell) from a positions file, or (None, None) if absent/empty."""
    if not os.path.exists(path):
        return None, None
    with open(path, encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    return doc.get("entities") or None, doc.get("cell")


def _render_png(svg_path: str, png_path: str) -> bool:
    if not which("rsvg-convert"):
        print("note: rsvg-convert not found on PATH; skipped PNG sanity check.")
        return False
    try:
        subprocess.run(["rsvg-convert", "-o", png_path, svg_path], check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"PNG render failed: {e}")
        return False


def cmd_edit(args) -> int:
    """Generate the standalone semi-manual editor, seeded from positions.yaml if present."""
    from .editor import build_editor_html
    cfg = _cfg(args)
    entities, _cell = _load_positions(args.positions)
    html = build_editor_html(cfg, entities)
    out_dir = os.path.dirname(args.out) or "."
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(html)
    n = sum(1 for e in entities.values() if e.get("type") == "tile") if entities else 0
    src = f"seeded from {args.positions}: {n} tiles" if entities else f"no {args.positions}; empty canvas"
    print(f"wrote {args.out}  ({src})")
    print(f"open it in a browser:  open {args.out}")
    return 0


def cmd_render(args) -> int:
    """Render the FINAL svg straight from a saved positions.yaml (no layout passes)."""
    from .render import render_positions_svg
    cfg = _cfg(args)
    entities, cell = _load_positions(args.positions)
    if not entities:
        print(f"render: no entities in {args.positions} (save it from the editor first).")
        return 1
    svg = render_positions_svg(entities, cfg, cell)
    out_dir = os.path.dirname(args.out) or "."
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(svg)
    tiles = {k: e for k, e in entities.items() if e.get("type") == "tile"}
    print(f"wrote {args.out}  ({len(tiles)} tiles, {len(entities) - len(tiles)} segments) from {args.positions}")

    # --- integrity checks on the placement ---
    odd = sorted(k for k, e in tiles.items() if int(e["x"]) % 2 != 0)
    print(f"even-x check: {'all tile x positions are even' if not odd else f'{len(odd)} tile(s) with ODD x: ' + ', '.join(odd[:12])}")
    tw = (cell or {}).get("w", cfg["layout"]["tile_width"])
    by_row: dict = {}
    for k, e in tiles.items():
        by_row.setdefault(int(e["row"]), []).append((float(e["x"]), k))
    overlaps = []
    for row, items in by_row.items():
        items.sort()
        for (xa, ka), (xb, kb) in zip(items, items[1:]):
            if xb - xa < tw:                     # tiles share a row and their x-intervals overlap
                overlaps.append((ka, kb, row, round(xb - xa)))
    if not overlaps:
        print("overlap check: no overlapping tiles")
    else:
        print(f"overlap check: {len(overlaps)} overlapping pair(s) (row, gap<{tw}):")
        for ka, kb, row, gap in overlaps[:12]:
            print(f"  row {row}: {ka} / {kb}  (x gap {gap})")

    png = os.path.splitext(args.out)[0] + ".png"
    if _render_png(args.out, png):
        print(f"wrote {png}")
    return 0


def main(argv=None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=DEFAULT_CONFIG, help="config YAML (default: %(default)s)")

    ap = argparse.ArgumentParser(prog="familytree", description="史记 family tree (semi-manual)")
    sub = ap.add_subparsers(dest="cmd")

    e = sub.add_parser("edit", parents=[common], help="generate the standalone HTML grid-positioning editor")
    e.add_argument("--out", default="build/editor.html", help="output HTML path (default: %(default)s)")
    e.add_argument("--positions", default=DEFAULT_POSITIONS,
                   help="seed the editor from this saved positions file if it exists (default: %(default)s)")
    e.set_defaults(func=cmd_edit)

    rd = sub.add_parser("render", parents=[common], help="render the final svg from a saved positions.yaml")
    rd.add_argument("--positions", default=DEFAULT_POSITIONS, help="saved positions file (default: %(default)s)")
    rd.add_argument("--out", default=DEFAULT_SVG, help="output SVG path (default: %(default)s)")
    rd.set_defaults(func=cmd_render)

    args = ap.parse_args(argv)
    if not getattr(args, "cmd", None):
        ap.print_help()
        return 1
    return args.func(args)
