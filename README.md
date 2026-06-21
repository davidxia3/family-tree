# 史記 family tree

A data-driven SVG genealogy of figures from 《史記》. The genealogy is stored as
**data** (people + relationships); a **layout** engine computes positions; a
**renderer** emits the SVG with connecting lines. No manual per-person coordinates.

## Layout
```
data/shiji.yaml        # the genealogy you hand-edit as you read
config.yaml            # layout + style knobs (optional; defaults in familytree/config.py)
familytree/
  model.py             # load YAML -> dataclasses + relationship index
  validate.py          # integrity checks (never crashes on partial data)
  layout.py            # tidy-tree + genealogy rules -> (x, y) per tile
  render.py            # positions -> SVG (all styling in <defs>/CSS)
  edit.py              # comment-preserving YAML edits for the CLI
  cli.py               # build | validate | status | add-person | set | add-marriage | add-descent
build/family_tree.svg  # generated
docs/PLACEMENT.md      # authoritative placement / layout rules
```

## Use
```bash
python3 -m familytree build      # data -> build/family_tree.svg (+ .png) + status
python3 -m familytree validate   # integrity report
python3 -m familytree status     # counts, roots, generations, unplaced

# add data (each re-validates, preserves your comments, and rebuilds):
python3 -m familytree add-person --id 帝嚳 --father 蟜極 --order 1
python3 -m familytree set --id 帝嚳 --note "代高辛氏"
python3 -m familytree add-marriage --husband 帝嚳 --wife 慶都
python3 -m familytree add-descent --person 劉累 --ancestor 帝堯 --with 夏孔甲帝

# review a new batch: outline the new tiles, then rebuild clean once confirmed
python3 -m familytree build --highlight 鯀,夏禹,夏啟
```
Requirements: Python 3.9+ with PyYAML (present); `rsvg-convert` for the PNG
sanity check (optional — the SVG is still written without it).

## Data model
- **Person**: `id` (== Chinese name, Traditional, stable & unique), `name` (display),
  optional `color` / `house` / `chapter` / `note`, and parent links
  `father_id` / `mother_id` / `birth_order` (1 = eldest among the anchor
  parent's children).
- **marriages**: `husband_id` / `wife_id`.
- **descended_from**: `person_id` / `ancestor_id` (soft "descended-of" link).

It is a DAG: a married-in daughter is placed beside her husband, with a dashed
link back to her father.

## Orientation
`orientation: rtl` (default) puts the senior person on the **right** and the
eldest child rightmost, matching classical Chinese reading. Layout is computed
left-to-right, then x is mirrored once at the end (glyphs stay upright).

## Placement rules
The full layout spec — generations, the one standardized gap, sibling packing,
wives, the DAG placement precedence, and descendant placement — is in
[docs/PLACEMENT.md](docs/PLACEMENT.md).
