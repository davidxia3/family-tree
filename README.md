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
python3 -m familytree add-descent --person 費昌 --ancestor 若木 --depth 4      # N rows below
python3 -m familytree add-descent --person 劉累 --ancestor 帝堯 --with 夏孔甲帝  # on a known row

# review a new batch: outline the new tiles, then rebuild clean once confirmed
python3 -m familytree build --highlight 鯀,夏禹,夏啟
```
Requirements: Python 3.9+ with PyYAML (present); `rsvg-convert` for the PNG
sanity check (optional — the SVG is still written without it).

## Data model
- **Person**: `id` (== Chinese name, **Traditional**, stable & unique, frozen once
  assigned — disambiguate true name-clashes with a suffix like `周定王-1`), `name`
  (display), optional `color` (`"#rrggbb"`), `house` / `chapter` / `note` (metadata),
  and parent links `father_id` / `mother_id` / `birth_order` (1 = eldest among the anchor
  parent's children).
- **marriages**: `husband_id` / `wife_id` (childless unions, married-in spouses).
- **descended_from**: `person_id` / `ancestor_id`, plus optional `depth: N` (render N rows
  below the ancestor) **or** `mentioned_with: X` (render on X's row).

It is a **DAG** (a daughter can be both a child and a wife). Every person is placed once.

## Placement & lineage rules
The authoritative spec is [docs/PLACEMENT.md](docs/PLACEMENT.md); the essentials:

- **Orientation** — `rtl` (default): senior on the **right**, eldest child rightmost.
  Computed left-to-right, then x is mirrored once (glyphs stay upright).
- **Generations & tiles** — one row per generation, uniform row pitch; vertical CJK tiles
  all the same height (sized to the longest name), names **top-aligned**. A person's
  `color` fills the tile; on a dark fill the text auto-switches to a light shade.
- **Spacing** — one standardized horizontal gap `h_gap` for siblings, husband-wife, AND
  wives alike. Sibling subtrees pack by **per-row tile contour** (closest tiles meet
  `h_gap`, never bounding-box separation); one vertical gap `v_gap` between rows.
- **Centering (rule E)** — a parent centers over the midpoint of ALL its children,
  *including* descendants and married-in/-out spouses.
- **Wives / mothers** — named mothers (and explicit wives) sit on the husband's row, to his
  **left**, ordered by the seniority of their eldest child; one tile per mother.
- **Placement precedence** — married-in spouse → under father → under mother → descendant
  → root. Roots form a forest; a **free component** (no edge to the main tree) is moved
  clear of it, kept at the top.
- **Descendants** (`descended_from`) — drawn as a phantom youngest child of the ancestor:
  unclear → direct youngest child; `depth: N` → N rows down (missing intermediates);
  `mentioned_with: X` → on X's row. A descendant who is also a spouse stays beside their
  partner (extra busbar child).
- **Married-out daughter** — if she weds a *free root* (no ancestry, no children), she stays
  under her father and the husband is drawn beside her (wife-left / husband-right).
- **Lines** — every lineage line is **solid and orthogonal** (horizontal/vertical only — no
  diagonal, no dashed). Child lines sprout from the **father alone**; the busbar splits at
  the vertical midpoint to the **closest** child; a drop forced to cross a bar gets a small
  gap (a clean "line hop").
