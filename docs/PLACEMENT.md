# Placement & layout rules

Authoritative spec for how the 史記 family tree is laid out and drawn. It reflects
what the code in [`familytree/layout.py`](../familytree/layout.py) and
[`familytree/render.py`](../familytree/render.py) actually does. If you change the
engine, update this file in the same commit.

---

## 0. Core principle

The genealogy is **data** (people + relationships). A layout engine computes every
coordinate; nothing is hand-placed. (The predecessor project failed by hard-coding
800+ tile positions and storing no relationships — never do that.) Pipeline:

```
data/shiji.yaml ──model── Dataset ──validate── report
                                   └──layout──  (x, y) per tile  ──render── SVG ──rsvg-convert── PNG
```

Keep `model` / `validate` / `layout` / `render` separate. All visual styling lives in
CSS inside the SVG `<defs>`; all sizes/spacing/colors come from `config.yaml`.

---

## 1. Data model (summary; schema lives in `data/shiji.yaml`)

**All Chinese — every `id` and `name` — is Traditional (繁體).**

- **Person** — `id` (the Chinese name; stable, unique, frozen once assigned; for a true
  name-clash between two different people, disambiguate with a suffix like `共伯-衛`,
  never derive ids from pinyin). `name` is the display string. Optional `color`
  (`"#rrggbb"`; quote it — a leading `#` is a YAML comment otherwise), `house`,
  `chapter`, `note` (metadata only — none of them auto-color anything).
- **Parent links live on the child**: `father_id`, `mother_id`, `birth_order`
  (`1` = eldest among the anchor parent's children; half-siblings share the father's
  ordering). `mother_id` must reference a *named* person record, or be null.
- **`marriages`** — `husband_id` / `wife_id` edge list (childless unions, married-in
  daughters).
- **`descended_from`** — `person_id` / `ancestor_id` / `mentioned_with` edge list
  (someone named only as a vague descendant). See rule X.

This is a **DAG**, not a tree: a daughter may be both a child (of her father) and a
wife (married elsewhere). Each person is drawn exactly once — see rule P.

---

## 2. Orientation (rule O)

Right-to-left, to match classical Chinese reading: the senior/primary person sits on
the **right**, and the eldest child is **rightmost**.

Implementation: the engine computes the whole layout in one canonical **left-to-right**
frame, then applies a **single horizontal mirror** of all x-coordinates at the very end.
Glyphs are never transformed — only tile center-x is negated — so text stays upright.
`orientation: ltr` in config disables the mirror.

---

## 3. Generations & tiles

- **Rule G — one row per generation.** Generation = depth in the placement forest
  (rule P). Rows are evenly pitched: `row_pitch = tile_height + v_gap`.
- **Rule T — tiles.** A name is a vertical stack of CJK characters. **Every tile is the
  same height**, sized to the **longest name in the dataset**. Names are **top-aligned**:
  characters start at the top with padding; any extra space trails at the **bottom**.
  Tile width is `char_box + 2·tile_pad`. A person's `color` fills only that tile (emitted
  as an inline `style`, so it beats the `.tile` class); on a **dark** fill the text
  auto-switches to `style.text_light` for contrast.

---

## 4. Horizontal packing (rules H, C, F)

- **Rule H — standardized gaps + per-row packing.** There is **one** horizontal gap,
  `h_gap` (edge-to-edge), used *everywhere*: between sibling subtrees, between husband
  and wife, and between consecutive wives.

  Sibling subtrees are packed as close together as possible (Reingold–Tilford "tidy
  tree"): a subtree's contour is the actual **tile positions per generation row**, not
  its bounding box. Two subtrees slide together until the closest pair of tiles **at
  some shared row** is exactly `h_gap` apart. Rows where only one subtree has a tile
  impose no constraint.

  So the example
  ```
  sib1:  X        sib2:  Y Y          packs as:  X Y Y        NOT:  X _ Y Y
         X X             _ Y                     X X Y              X X _ Y
  ```
  (Binding row gap = `h_gap`; the deeper tail extends down freely.)

- **Rule C — children order.** Children are laid oldest→youngest in the canonical frame,
  so after the mirror the **eldest is rightmost**. Sort key: `birth_order` ascending
  (missing birth_order sorts last), then name, then id.

- **Rule F — a father is centered** over the midpoint of his first and last child.
  Child lineage lines descend from the **father alone**, never from the husband–wife
  marriage tie.

---

## 5. Wives & mothers (rules W, M)

- **Rule W — wife tiles.** A named **mother** of someone whose **father is also present**,
  and any explicit `marriages` wife, is drawn as a *wife tile* attached to the husband —
  not as a standalone node. She sits on the husband's row, offset to his **left**
  (canonically to his right, before the mirror), one `h_gap` away.

- **Rule M — wife order (slots).** Wives are ordered by the **seniority of their most-
  senior child**: the mother of the eldest child is directly beside the father, the
  mother of the next-eldest to her left, and so on. **One tile per mother** even if she
  bore several children (she takes the slot of her most-senior child). Childless wives
  sort after the child-bearing ones. Unnamed mothers get no tile and no slot, so the
  order closes up.

  The father + his wives form a single **composite block** for sibling packing (its full
  width keeps `h_gap` from neighbors), and the children subtree is centered under the
  **father**, who sits at the right end of that block.

- **Rule N — no father (rule 7).** If a child has a named mother but no father, the mother
  is the anchor and is centered over the children. *Partial implementation*: the basic
  single-anchor-mother case works; **multiple co-mothers under one fatherless anchor is
  not implemented yet** — harden when first needed.

---

## 6. Primary placement / the DAG (rules P, D)

- **Rule P — each person is placed exactly once**, by this precedence:
  1. **married-in spouse** → beside the spouse (a wife tile, rule W);
  2. else **under the father**;
  3. else **under the named mother** (rule N);
  4. else as a **descendant** phantom child (rule X);
  5. else it is a **root**.

  Roots form a forest: they are packed left-to-right like siblings of a virtual
  super-root, at `h_gap`.

- **Rule D — married-in daughter.** A daughter who marries someone in the chart is placed
  beside her husband (rule W); her link to her father is drawn as a **dashed secondary
  edge**. This is the *only* dashed edge type.

---

## 7. Descendant-only people (rule X — "note 3")

For someone named only as a vague descendant (`descended_from`):

- **Horizontal** = the position of a **hypothetical youngest child of the ancestor**. We
  pretend the ancestor had one more child, junior to all the real ones (so in rtl it sits
  to their **left**); the ancestor centers over the real children **and** this phantom.
- **Vertical** = the generation row of **`mentioned_with`** — the figure during whose
  story the descendant appears (not the ancestor's child row).
- **Line** = a **solid** line from the ancestor to the descendant, identical to a normal
  child line except it **extends further down** to reach that lower row.

Example: 劉累 is an unclear descendant of 帝堯, mentioned during the story of 夏孔甲帝.
So 劉累 is drawn as 帝堯's phantom youngest child (left of 丹朱) but dropped down onto
夏孔甲帝's row, joined to 帝堯 by a long solid line.

If `mentioned_with` is missing or unknown, the descendant falls back to the ancestor's
normal child row (and `validate` warns).

---

## 8. Edges & line styles

| Edge | Style | Drawn between |
|------|-------|---------------|
| Lineage | **solid** busbar (parent ↓ to a horizontal bar over all children ↓ to each child) | parent → children (incl. descendant phantom children, rule X) |
| Marriage | **solid** tie | husband → wife₁ → wife₂ … (consecutive slots) |
| Secondary | **dashed** | married-in daughter → her father (rule D) only |

**Children sprout from the father only.** The lineage busbar rises from the **father's**
bottom edge — never from the husband–wife marriage tie, which is an independent horizontal
segment between the spouses. (With no father, the busbar rises from the anchoring mother,
rule N.)

Tiles are drawn last, on top of the edges.

---

## 9. Config knobs (`config.yaml`)

| Key | Meaning |
|-----|---------|
| `orientation` | `rtl` (senior on right) or `ltr` (no mirror) |
| `layout.char_box` | px box per stacked character |
| `layout.tile_pad` | px padding inside a tile |
| `layout.h_gap` | the one standardized horizontal gap (rule H) |
| `layout.v_gap` | vertical gap between a tile's bottom and the next row |
| `layout.margin` | canvas padding |
| `layout.tile_radius` | tile corner radius |
| `style.*` | colors, fonts, stroke widths, dash pattern — all emitted as CSS |

Defaults live in [`familytree/config.py`](../familytree/config.py); `config.yaml` is
deep-merged on top.

---

## 10. Robustness

- Partial data never crashes: unknown references are skipped and reported; the renderer
  draws what it can; unplaced people are listed by `status`.
- Lineage cycles are detected by `validate` and guarded against in `layout` (no infinite
  recursion).

---

## 11. Change log (decisions made while building)

- **Format & ids** — YAML (inline comments let David annotate as he reads); `id` is the
  Chinese name (avoids the pinyin collisions that sank the previous attempt).
- **Uniform tile height** — all tiles sized to the longest name (was per-name height).
- **Standardized spacing** — collapsed separate sibling/wife gaps into one `h_gap`;
  **husband–wife distance now equals the sibling gap**. Renamed `row_gap`→`v_gap`.
- **Top-aligned names** — was vertically centered; now top-aligned with trailing space.
- **Descendant rule (X)** — was a dashed edge with the person on the ancestor's row. Now
  a phantom-youngest-child placement: solid line, x from the ancestor's child slot, y from
  the new `mentioned_with` field. `descended_from` is no longer a dashed edge.
- **Per-person color** — emitted as an inline `style` (beats the `.tile` class); a dark
  fill auto-switches the text to a light shade (`text_light`). Two different people who
  share a name get a suffixed id while the display `name` stays bare — e.g. the two 殷太丁
  (湯's son / 武乙's son) are ids `殷太丁` and `殷太丁-武乙`, both shown as 殷太丁.
- **Review highlight** — `build --highlight "id,…"` outlines tiles (render-time only) so a
  new batch can be eyeballed before the outlines are cleared.

## 12. Known limitations / TODO

- Rule N: multiple co-mothers under a single fatherless anchor (full rule 7) — basic only.
- A descendant's reserved column is only enforced at the ancestor's child row, not all the
  way down to its rendered row; with dense neighbors a long descendant line could pass
  near other tiles. Revisit if it occurs in real data.
- Cycle detection in `validate` is recursive; fine for realistic depths.
