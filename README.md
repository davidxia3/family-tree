# 史記 family tree

A semi-manual SVG genealogy of figures from 《史記》. There is **no relationship
database** — every tile is placed by hand. `positions.yaml` is the single,
self-contained data file: one entity per tile (carrying its own **name** and
**color**) plus the connector lines you draw. An editor places them; a renderer
emits the SVG.

## Workflow
1. **Add tiles.** Give a list of *name → color* and one tile is created per name,
   placed **one per row in a vertical column** starting at the first row (same `x`,
   `row` 0, 1, 2, …) in `positions.yaml`.
2. **Arrange.** `python -m familytree edit` → open `build/editor.html`, drag tiles
   (shift+drag), anchor subtrees (right-click), draw lines (Busbar / Marriage / Top
   stub / +H / +V), add line hops (+ Hop), then **Save positions.yaml** and put it
   in the repo root.
3. **Render.** `python -m familytree render` → `build/family_tree.svg`.

```bash
python -m familytree edit        # positions.yaml -> build/editor.html
python -m familytree render      # positions.yaml -> build/family_tree.svg (+ checks)
```
The editor autosaves to the browser's localStorage, so closing/reopening
`build/editor.html` restores your work; `positions.yaml` is the durable, git-tracked
source of truth. See the docstring at the top of `familytree/editor.py` for the full
editor spec.

## Files
```
positions.yaml         # THE data: tiles (name + color + x/row/anchor) and lines
config.yaml            # sizes / spacing / colour pairs (defaults in familytree/config.py)
familytree/
  config.py            # load config.yaml; derive gaps, char pitch, line/border widths
  editor.py            # generate the standalone HTML grid-positioning editor
  render.py            # positions.yaml -> SVG (all styling in <defs>/CSS)
  cli.py               # edit | render
build/editor.html      # generated editor (open in any browser; file:// works)
build/family_tree.svg  # generated final output
```

## positions.yaml
```yaml
cell: {w: 64, h: 308, pitch: 436}     # geometry the coords were saved at
entities:
  "黃帝": {type: tile, anchor: 少典, x: 3056, row: 2, name: "黃帝", color: wudi}
  "少典": {type: tile, anchor: ~,   x: 2354, row: 1, name: "少典"}            # no color -> default tile
  "seg1": {type: vseg, anchor: 黃帝, x: 3088, y1: 808, y2: 872}               # a line
  "seg2": {type: hseg, anchor: 黃帝, y: 1244, x1: 1860, x2: 4316, hops: [3000]}  # line with a hop
```
- **tile**: `name` is the display text; `color` is a **key** into the `colors` map in
  `config.yaml` (omit / `~` for the default tile). `x` is the left edge; `y = row * pitch`.
  The editor labels tiles by their **id** (the unique key); ids may be disambiguated
  (e.g. `周定王-1`) while `name` stays the displayed text.
- **hseg / vseg**: a connector line; `hops` cut small gaps so a line can hop a crossing.
- **anchor**: ≤ 1 per entity — dragging an entity carries everything anchored to it.

## Styling (config.yaml)
Tile primitives are `tile_width`, `tile_height`, `font_size`, `line_width`,
`border_width`, `line_hop_length`; gaps and char pitch derive from them. Colours are
named **fill/text pairs** under `colors:`; a tile's `color` is a key into that map.

Requirements: Python 3.9+ with PyYAML; `rsvg-convert` for the optional PNG sanity
check. Set `PYTHONUTF8=1` on Windows so CJK prints to the console.
