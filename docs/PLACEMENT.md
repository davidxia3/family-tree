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
- **`descended_from`** — `person_id` / `ancestor_id` edge list (someone named only as a
  descendant). Optional `depth` (generations below the ancestor) **or** `mentioned_with`
  (a person whose row to render on), and optional `order` (rank among the ancestor's phantom
  descendants, 1 = senior/rightmost). See rule X.
- **`siblings`** — a list of parentless sibling groups, each a list of member ids **eldest
  first**, for people named as siblings whose shared parent is not a tile here. See rule Sib.

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
- **Rule E — descendants count for centering.** ALL of a person's descendants count as
  "children" for rule F: phantom-child descendants (rule X) and extra busbar children
  (married-in daughters, rule D; and spouse-descendants). The ancestor is centered over the
  span of all of them. For an extra busbar child whose x is fixed by a marriage elsewhere,
  the ancestor re-centers over it as a final step (exact for roots; e.g. 少典 ends up
  between 黃帝 and 女華).

---

## 5. Wives & mothers (rules W, M)

- **Rule W — wife tiles.** A named **mother** of someone whose **father is also present**,
  and any explicit `marriages` wife, is drawn as a *wife tile* attached to the husband —
  not as a standalone node. She sits on the husband's row, offset to his **left**
  (canonically to his right, before the mirror), one `h_gap` away.

- **Rule M — wife order (slots).** Wife order is set **manually**, by the order the wives
  appear in the `marriages` list for that husband: the first-listed sits directly beside the
  father (slot 1), the next to her left, and so on. (To reorder wives, reorder their
  `marriages` entries.) **One tile per mother** even if she bore several children. A wife
  known *only* as a mother (no `marriages` entry) is appended after the listed ones, by her
  most-senior child then id. Unnamed mothers get no tile and no slot, so the order closes up.
  *(There is no automatic child-seniority ordering — that rule was removed.)*

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
  super-root, at `h_gap`. A **free component** — a root whose whole tree shares no edge
  (parent, marriage, or descent) with the main tree — can sit anywhere, so it is moved
  clear of the main tree (off to one side, keeping its own top rows) and never overlaps.

- **Rule D — married-in daughter.** A daughter who marries a placed man (one with his own
  ancestry/line) is placed beside her husband (rule W) but is still an **extra busbar child**
  of her father: he centers over her too (rule 4 / rule E below) and a **solid orthogonal**
  lineage line runs to her — no dashed edges. (Lines are never diagonal or dashed.)

- **Rule D2 — married-out daughter (free-root husband).** If a daughter marries a **free
  root** — a husband with no ancestry and no children of his own — the roles flip: the
  *daughter stays a node under her father* (solid line, no dashed edge) and the husband is
  drawn as a spouse tile **beside her**. Left/right is preserved: wife on the left, husband
  on her **right**. (So the root is brought down next to the daughter, not the daughter
  pulled up to the root.) e.g. 繆嬴 (秦莊公's daughter) and 西戎豐王.

- **Rule L — in-law family (a wife's natal kin).** When a **root** has a daughter who married
  **into** the main tree (she is a wife-tile beside her husband, rule W) and the root has his
  own spouse/children, that root is an *in-law*. Left alone he would sit at row 0 and scatter
  his family to the top with a full-height connector. Instead:
  1. **Row** — hang the root **one row above** the daughter's marriage row, and shift his whole
     natal subtree down by the same delta, so his other children land on the daughter's row.
  2. **X** — the daughter's marriage row is the densest in the chart (her husband, co-wives and
     his siblings fill it), so there is **no adjacent slot**. Park the natal block just **past
     the right edge** of that row (clear of the cluster), then **center the root over [his real
     children + the married-in daughter]** so his solid busbar reaches her, and slide his wife
     tile along with him. The busbar may share the inter-row band with the daughter's
     father-in-law's busbar (both at the same split height) — unavoidable when she sits interior
     to that span.
  *Single married-in daughter per root; multiple would over-constrain the row shift.* This is a
  capability for when the in-law **parent** should be shown; when the parent is NOT in the tree,
  use rule Sib instead (that is what the 呂后/周呂侯 case does).

- **Rule Sib — parentless siblings (the `siblings` edge).** People Shiji names as siblings but
  whose shared parent is not a tile here. If one member married **into** the tree (a wife-tile
  beside her partner, rule W), the other members are attached to that partner on the partner's
  **senior (right, rtl) side**, eldest-first — so an elder brother sits just right of the
  husband. They share the married member's row. The group is tied by a **stub-less sibling
  busbar**: like a family busbar but with NO parent stem rising from its middle. That bar is the
  one that **hops** where it crosses a real lineage drop — the crossed lineage line (e.g.
  漢太上皇 → 漢高祖) stays fully **solid**. The bar sits at `top - v_gap/4` (not the usual
  `-v_gap/2`) so it clears the row's parent busbar and crosses the straddled drop in its interior.
  e.g. 周呂侯 (elder) sits right of 漢高祖, tied to his sister 呂后 (who married 漢高祖) by a bar
  that hops over 漢高祖's drop.

---

## 7. Descendant-only people (rule X)

Someone named only as a descendant (`descended_from`) is drawn as a **phantom youngest
child of the ancestor**: the ancestor "pretends" to have one more child, junior to all the
real ones (so in rtl it sits to their **left**), centers over the real children **and**
this phantom, and a **solid** line is drawn to it (it may run further down than a normal
child line). The descendant may itself have a normal subtree below it. When an ancestor has
**several** phantom descendants, their order among themselves is set by the edge's optional
**`order`** (1 = senior = **rightmost** in rtl; they still sit left of any real children). e.g.
劉累's 漢太上皇 (`order: 1`, right branch) and 劉賈 (`order: 2`, left branch). Three placements,
by what the edge carries:

- **Rule X-a — unclear (`depth`/`mentioned_with` both absent):** place as a plain **direct
  youngest child** (one row down). Use when the exact descent is unknown. e.g. 女修 ←
  帝顓頊; 趙衰 ← 造父.
- **Rule X-b — known degree, missing intermediates (`depth: N`):** **preserve generation
  depth** — render `N` rows below the ancestor, as if the missing fathers were there.
  e.g. 費昌 is the great-great-grandson of 若木 → `depth: 4`; 孟戲/中衍 are great-great-
  grandsons of 大廉 → `depth: 4`. A descendant placed this way carries its own subtree
  (e.g. 中潏 `depth: 4` under 中衍, then the whole 秦 line hangs below 中潏).
- **Rule X-c — mentioned with a known figure (`mentioned_with: X`):** render on **X's
  generation row** — and re-base the descendant's **whole natal subtree** with it, so its
  children land one row below it, and so on. (Without this, a `mentioned_with` person who has
  descendants would sit deep while the descendants rendered shallow — a vertical split.)
  e.g. 劉累 ← 帝堯, mentioned during 夏孔甲's story → drops onto 夏孔甲's row; and the whole 漢
  line hangs below 漢太上皇 (← 劉累, mentioned with 秦公子嬰 → 漢太上皇 on 子嬰's row, 漢高祖 one
  row below, his children below that). Chained references settle by iterating to a fixpoint
  (ancestors first). The phantom still **reserves a half-width slot at the ancestor's child
  row**, so it stays beside the ancestor's real children (to their left, rule X) even though
  its own tile renders far below — e.g. 劉累 sits left of 帝堯's son 丹朱, not stacked under him.

**Long-descent lane (no crossings).** A `mentioned_with` phantom with a deep subtree (e.g. 劉累 →
the 漢 line ~40 rows below) has a connecting busbar that runs through many otherwise-empty rows.
Those rows reserve the busbar's **x-lane** (narrow at the stem, the full child-span at the bus
bar and drops) in the contour, so a neighbouring column (e.g. 周, whose cadet branches drift
right as it descends) cannot slide under the line and cross it. The tidy-tree packer then keeps
the lane clear with the **minimal** shift and **re-centers every ancestor** automatically (e.g.
帝堯 moves right just enough to clear 周's rightmost descendant, and 帝嚳 → 玄囂 → 黃帝 → 少典
re-center over their children in turn). No manual coordinates.

**Exception — a descendant who is also a married-in spouse.** If the `descended_from` person
is a wife/spouse tile (placed beside their partner by rule W), they are *not* re-placed as a
phantom child. Instead they stay beside their partner and become an **extra busbar child** of
the ancestor: the ancestor centers over them (rule E) and a **solid orthogonal** lineage line
runs to them. e.g. 女華 is 大業's wife and a descendant of 少典, so 少典 sits between 黃帝 and
女華 with a solid line dropping down the left to 女華.

---

## 8. Edges & line styles

| Edge | Style | Drawn between |
|------|-------|---------------|
| Lineage | **solid** busbar (parent ↓ to a split bar over all children ↓ to each child) | parent → children: real children, phantom-child descendants (rule X), and extra busbar children — married-in daughters (rule D) and spouse-descendants |
| Marriage | **solid** tie | husband → wife₁ → wife₂ … (consecutive slots) |

**All lines are orthogonal and solid** — only horizontal/vertical segments, never diagonal,
never dashed. Where a vertical drop is *forced* to cross another bar, it is broken with a
small gap (a clean "line hop"); the crossed bar stays solid.

**Children sprout from the father only.** The lineage busbar rises from the **father's**
bottom edge — never from the husband–wife marriage tie, which is an independent horizontal
segment between the spouses. (With no father, the busbar rises from the anchoring mother,
rule N.)

**Rule S — split height.** The busbar (where the line branches to the children) always sits
**one row below the father** — at the height it would have if the children were direct children
one tile down (`father_bottom + v_gap/2`), regardless of how far the actual children render.
The drops then extend down to each child's real depth. For ordinary children one row below this
is the obvious midpoint; for a **long descendant-of line** (e.g. 劉累 → the 漢 line ~40 rows
below, or 大廉 → 孟戲/中衍 four rows below) the bar stays **high** (just under the father) and the
drops run long — rather than the bar sinking to the midpoint of the deep gap. (Earlier rule:
split at the midpoint to the *closest* child — changed because a deep-only descent then put the
bar halfway down the chart.)

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
- **Descendant rule (X)** — `descended_from` is a solid phantom-youngest-child placement
  (not a dashed edge). Three forms: unclear → direct youngest child; `depth: N` → N rows
  below the ancestor (missing intermediates); `mentioned_with: X` → on X's row.
- **`mentioned_with` carries its subtree** — a `mentioned_with` descendant is re-based onto the
  referent's row together with everything beneath it (fixpoint pass, ancestors first), so a
  dynasty hung off a distant ancestor (漢 ← 劉累 ← 帝堯) renders at the right depths instead of
  splitting vertically. It still reserves a half-width slot at the ancestor's child row so it
  stays beside real siblings (rule X) — was: packed at the child row and rendered down.
- **Split height now one row below (rule S)** — the busbar always branches one row under the
  father (`father_bottom + v_gap/2`), so a long descendant-of line keeps its bar high and drops
  long, instead of sinking the bar to the midpoint of the deep gap. Was: midpoint to the closest
  child.
- **Phantom descendant order** — `descended_from` takes an optional `order` (1 = senior/right) to
  rank multiple phantom descendants of one ancestor. e.g. 劉累's 漢太上皇 (1, right) vs 劉賈 (2, left).
- **Verification grid** — `build --grid` draws a faint background grid (a numbered line per
  generation row, every 5th emphasised, plus verticals one tile-width apart) to eyeball
  placements; render-time only, like `--highlight`.
- **Busbar split (rule S, original)** — the lineage line branches at the vertical midpoint between
  the father and the *closest* child (handles children at mixed depths).
- **Married-out daughter (rule D2)** — a daughter who weds a free root keeps her place
  under her father; the root husband is drawn as a spouse tile to her right.
- **In-law family (rule L)** — a root whose daughter married into the tree is hung one row
  above her (its natal subtree shifted to match) and parked just past the dense marriage row,
  then centered over its children + the daughter, with its wife sliding along — so a wife's
  parents/siblings sit beside her instead of scattering to row 0. (Capability for when the
  in-law parent is shown.)
- **Manual wife order** — removed the automatic "order wives by their senior child" rule; wife
  slot order is now the `marriages`-list order (reorder the entries to reorder wives).
- **Parentless siblings (rule Sib)** — a `siblings` edge groups people named as siblings with no
  parent tile; if one married in, the others attach beside that spouse's partner (elder on the
  senior side) and a **stub-less** sibling busbar ties them. That bar (not the crossed lineage
  drop) carries the line-hop. e.g. 周呂侯 right of 漢高祖, tied to 呂后. (Replaces the rule-L
  treatment for the 呂 family — 呂公/呂媼 are no longer tiles.)
- **Long-descent lane** — a `mentioned_with` phantom with a deep subtree reserves its busbar's
  x-lane through the empty intermediate rows, so a neighbour (周) can't slide under the line; the
  packer then shifts the branch the minimal amount and re-centers all ancestors (e.g. 帝堯 right,
  off 周).
- **Per-person color** — emitted as an inline `style` (beats the `.tile` class); a dark
  fill auto-switches the text to a light shade (`text_light`). Two different people who
  share a name get a suffixed id while the display `name` stays bare — e.g. the two 周定王
  are ids `周定王-1` / `周定王-2`, both shown as 周定王 (give one a distinct display name,
  like 殷子太丁, when you want to tell them apart on the chart).
- **No dashed/diagonal lines (rules E + line-hop)** — married-in daughters and spouse-
  descendants are no longer dashed diagonals; they are **extra busbar children** drawn with
  solid orthogonal lines, and the ancestor centers over them too (rule E). Every line is
  horizontal/vertical; a vertical that must cross a bar is broken with a small gap (line hop).
- **Free components moved aside** — a root whose whole tree connects to the main tree by no
  edge is shifted clear of it (kept at the top, off to one side) so it can never overlap.
- **Review highlight** — `build --highlight "id,…"` outlines tiles (render-time only) so a
  new batch can be eyeballed before the outlines are cleared.

## 12. Known limitations / TODO

- Rule N: multiple co-mothers under a single fatherless anchor (full rule 7) — basic only.
- Both a `depth:` and a `mentioned_with:` descendant pack at their own **deep rendered row** (so
  a long subtree is spaced against other deep columns), reserving a slot at the ancestor's child
  row plus the busbar's x-lane through the intermediate rows (so neighbours can't cross the
  line). Only `mentioned_with:` phantoms reserve the lane; a `depth:` chain (e.g. the 秦 line)
  does not yet — add it there too if a crossing appears.
- **Parentless siblings (rule Sib)** assume **one** member married into the tree (the others
  attach beside that partner). A group where none married in (free-floating siblings) would fall
  back to roots and is not specially placed yet. **In-law parents (rule L)** handle a single
  married-in daughter per root; two would over-constrain the row shift.
- The sibling / in-law busbar can share the inter-row band with the crossed family's busbar
  (cosmetic, unavoidable when the married-in member sits interior to that span); rule Sib's bar
  is dropped to `top - v_gap/4` to keep the crossing clean.
- Cycle detection in `validate` is recursive; fine for realistic depths.
