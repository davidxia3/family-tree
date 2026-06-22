"""Command-line interface:  python3 -m familytree <command>

  build     data -> build/family_tree.svg (+ .png sanity check) + status
  validate  print the full integrity report
  status    counts, roots, generations, unplaced people
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
from shutil import which

from . import edit as _edit
from .config import load_config
from .layout import compute_layout
from .model import load_dataset
from .render import render_svg
from .validate import ERROR, WARN, validate

DEFAULT_DATA = "data/shiji.yaml"
DEFAULT_CONFIG = "config.yaml"
DEFAULT_SVG = "build/family_tree.svg"


def _load(args):
    cfg = load_config(args.config if os.path.exists(args.config) else None)
    ds, problems = load_dataset(args.data)
    return ds, cfg, problems


def _print_issues(issues) -> int:
    if not issues:
        print("validate: no issues.")
        return 0
    for lvl, msg in issues:
        print(f"  [{lvl}] {msg}")
    errs = sum(1 for lvl, _ in issues if lvl == ERROR)
    warns = sum(1 for lvl, _ in issues if lvl == WARN)
    infos = len(issues) - errs - warns
    print(f"validate: {errs} error(s), {warns} warning(s), {infos} info.")
    return errs


def cmd_validate(args) -> int:
    ds, _cfg, problems = _load(args)
    issues = [(ERROR, m) for m in problems] + validate(ds)
    _print_issues(issues)
    return 0


def cmd_status(args) -> int:
    ds, cfg, _problems = _load(args)
    lay = compute_layout(ds, cfg)
    by_gen = {}
    for tile in lay.tiles.values():
        by_gen[tile.gen] = by_gen.get(tile.gen, 0) + 1
    span = (max(by_gen) + 1) if by_gen else 0
    print(f"people:          {len(ds.people)}")
    print(f"marriages:       {len(ds.marriages)}")
    print(f"descended_from:  {len(ds.descended_from)}")
    print(f"placed tiles:    {len(lay.tiles)}")
    print(f"roots:           {len(lay.roots)}  [{', '.join(lay.roots)}]")
    print(f"generations:     {span}  (by row: {dict(sorted(by_gen.items()))})")
    if lay.unplaced:
        print(f"unplaced:        {len(lay.unplaced)}  [{', '.join(lay.unplaced)}]")
    else:
        print("unplaced:        0")
    return 0


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


def cmd_build(args) -> int:
    ds, cfg, problems = _load(args)
    issues = [(ERROR, m) for m in problems] + validate(ds)
    _print_issues(issues)

    lay = compute_layout(ds, cfg)
    raw = getattr(args, "highlight", "") or ""
    highlight = {s for s in re.split(r"[,\s]+", raw.strip()) if s}
    svg = render_svg(lay, cfg, highlight=highlight)
    out_dir = os.path.dirname(args.out) or "."
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"wrote {args.out}  ({lay.width:.0f} x {lay.height:.0f})")
    if highlight:
        print(f"highlighted {len(highlight)} tile(s) for review: {', '.join(sorted(highlight))}")

    png = os.path.splitext(args.out)[0] + ".png"
    if _render_png(args.out, png):
        print(f"wrote {png}")

    print("--- status ---")
    cmd_status(args)
    return 0


def _save_and_build(args, lines, summary: str) -> int:
    """Validate the edited text, write it, then rebuild (unless --no-build)."""
    ok, err = _edit.parse_ok(lines)
    if not ok:
        print(f"aborted: edit would make {args.data} invalid YAML:\n  {err}")
        return 1
    _edit.write_lines(args.data, lines)
    print(summary)
    if getattr(args, "no_build", False):
        return cmd_validate(args)
    return cmd_build(args)


def cmd_add_person(args) -> int:
    ds, _cfg, _problems = _load(args)
    if args.id in {p.id for p in ds.people}:
        print(f"error: id {args.id!r} already exists.")
        return 1
    lines = _edit.read_lines(args.data)
    item = _edit.person_item_lines(
        args.id, name=args.name, father=args.father, mother=args.mother, order=args.order,
        color=args.color, house=args.house, chapter=args.chapter, note=args.note,
    )
    if ds.people:                      # blank line between records (matches the seed style)
        item = [""] + item
    _edit.append_item(lines, "people", item)
    return _save_and_build(args, lines, f"added person {args.id}")


def cmd_set(args) -> int:
    ds, _cfg, _problems = _load(args)
    if args.id not in {p.id for p in ds.people}:
        print(f"error: id {args.id!r} not found.")
        return 1
    fields = {}
    for key, val in (("father_id", args.father), ("mother_id", args.mother),
                     ("birth_order", args.order), ("color", args.color), ("house", args.house),
                     ("chapter", args.chapter), ("note", args.note)):
        if val is not None:
            fields[key] = val
    if not fields:
        print("error: nothing to set (pass --father/--mother/--order/--color/...).")
        return 1
    lines = _edit.read_lines(args.data)
    if not _edit.set_person_fields(lines, args.id, fields):
        print(f"error: could not locate the {args.id!r} record block.")
        return 1
    return _save_and_build(args, lines, f"updated {args.id}: {', '.join(fields)}")


def cmd_add_marriage(args) -> int:
    lines = _edit.read_lines(args.data)
    item = [f"  - {{husband_id: {_edit.scalar(args.husband)}, wife_id: {_edit.scalar(args.wife)}}}"]
    _edit.append_item(lines, "marriages", item)
    return _save_and_build(args, lines, f"added marriage {args.husband} -- {args.wife}")


def cmd_add_descent(args) -> int:
    lines = _edit.read_lines(args.data)
    fields = f"person_id: {_edit.scalar(args.person)}, ancestor_id: {_edit.scalar(args.ancestor)}"
    if args.depth is not None:
        fields += f", depth: {args.depth}"
    if args.mentioned_with:
        fields += f", mentioned_with: {_edit.scalar(args.mentioned_with)}"
    _edit.append_item(lines, "descended_from", [f"  - {{{fields}}}"])
    return _save_and_build(args, lines, f"added descended_from {args.person} <- {args.ancestor}")


def main(argv=None) -> int:
    # --data / --config live on a shared parent so they work AFTER the
    # subcommand (e.g. `add-person --id X --data foo.yaml`), which is the
    # natural order.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data", default=DEFAULT_DATA, help="genealogy YAML (default: %(default)s)")
    common.add_argument("--config", default=DEFAULT_CONFIG, help="config YAML (default: %(default)s)")

    ap = argparse.ArgumentParser(prog="familytree", description="史记 family tree builder")
    sub = ap.add_subparsers(dest="cmd")

    b = sub.add_parser("build", parents=[common], help="generate the SVG (+ PNG) and print status")
    b.add_argument("--out", default=DEFAULT_SVG, help="output SVG path (default: %(default)s)")
    b.add_argument("--highlight", default="", help="comma/space-separated ids to outline (transient new-batch review)")
    b.set_defaults(func=cmd_build)

    v = sub.add_parser("validate", parents=[common], help="print the integrity report")
    v.set_defaults(func=cmd_validate)

    s = sub.add_parser("status", parents=[common], help="print counts / roots / unplaced")
    s.set_defaults(func=cmd_status)

    def _build_flags(p):
        p.add_argument("--no-build", action="store_true", help="edit only; don't regenerate the SVG")
        p.add_argument("--out", default=DEFAULT_SVG, help=argparse.SUPPRESS)

    ap_p = sub.add_parser("add-person", parents=[common], help="append a new person, then rebuild")
    ap_p.add_argument("--id", required=True)
    ap_p.add_argument("--name")
    ap_p.add_argument("--father")
    ap_p.add_argument("--mother")
    ap_p.add_argument("--order", type=int, help="birth_order (1 = eldest)")
    ap_p.add_argument("--color")
    ap_p.add_argument("--house")
    ap_p.add_argument("--chapter")
    ap_p.add_argument("--note")
    _build_flags(ap_p)
    ap_p.set_defaults(func=cmd_add_person)

    ap_s = sub.add_parser("set", parents=[common], help="set fields on an existing person, then rebuild")
    ap_s.add_argument("--id", required=True)
    ap_s.add_argument("--father")
    ap_s.add_argument("--mother")
    ap_s.add_argument("--order", type=int, help="birth_order (1 = eldest)")
    ap_s.add_argument("--color")
    ap_s.add_argument("--house")
    ap_s.add_argument("--chapter")
    ap_s.add_argument("--note")
    _build_flags(ap_s)
    ap_s.set_defaults(func=cmd_set)

    ap_m = sub.add_parser("add-marriage", parents=[common], help="append a marriage, then rebuild")
    ap_m.add_argument("--husband", required=True)
    ap_m.add_argument("--wife", required=True)
    _build_flags(ap_m)
    ap_m.set_defaults(func=cmd_add_marriage)

    ap_d = sub.add_parser("add-descent", parents=[common], help="append a descended-from link, then rebuild")
    ap_d.add_argument("--person", required=True)
    ap_d.add_argument("--ancestor", required=True)
    ap_d.add_argument("--depth", type=int, help="generations below the ancestor (missing intermediates)")
    ap_d.add_argument("--with", dest="mentioned_with", help="figure whose generation row the descendant is drawn on")
    _build_flags(ap_d)
    ap_d.set_defaults(func=cmd_add_descent)

    args = ap.parse_args(argv)
    if not getattr(args, "cmd", None):
        ap.print_help()
        return 1
    if not hasattr(args, "out"):
        args.out = DEFAULT_SVG
    return args.func(args)
