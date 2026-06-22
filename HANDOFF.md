# Handoff prompt — 史記 family tree

Paste the block below to kick off a new Claude Code session continuing this work.

---

You're continuing a data-driven SVG genealogy of figures from 《史記》 (Shiji), using **only**
Shiji as the source. **Read `CLAUDE.md` and `docs/PLACEMENT.md` first** — they're authoritative
for conventions and the full layout/lineage rules. Your persistent memory also has a project
overview. The core principle: the genealogy is DATA (`data/shiji.yaml`); a layout engine
computes every coordinate; a renderer emits the SVG. **No manual per-person coordinates.**

**Where it stands:** `data/shiji.yaml` has **253 people across 54 generations** — 少典 → 黃帝,
the 五帝, and the 夏 / 殷 / 周 / 秦 dynasties, plus 西楚 (項羽) and two disconnected "free"
components (少暤, 項燕). `python3 -m familytree build` is clean (`validate: no issues`); it writes
`build/family_tree.svg` and a `.png` you can Read to self-check (you see PNGs, not SVGs;
`rsvg-convert` renders them — to inspect one region of the now-tall chart, crop the SVG's
viewBox/height and re-render).

**How we work:** David reads Shiji and describes people in natural language ("X, son of Y;
color Z" / "X: descendant of Y"). You translate into `data/shiji.yaml`, keep ids stable,
`build`, and **verify by reading the PNG**. When adding a batch, build with
`--highlight "id1,id2,…"` so David can eyeball the new tiles; once he confirms, rebuild without
`--highlight`. Always **flag judgment calls** (ambiguous birth_order, Simplified→Traditional
fixes, name collisions, inferred mothers) and let him confirm before/just-after applying.

**Conventions that bite if missed:**
- All Chinese — ids AND display names — is **Traditional (繁體)**; convert anything Simplified
  he sends and flag it. `id` == the name, stable & **frozen**.
- Two different people who share a name → suffixed ids (`周定王-1`/`周定王-2`) with the bare
  display `name`. (Renames/re-parenting are manual YAML edits — update the record AND every
  reference; replace-all on the id string works.)
- Colors are per-dynasty (gold 五帝, verdigris 夏, dark-red 殷, purple 周, black 秦, olive 西楚);
  David marks batch names with an **X** to mean "give this the dynasty color."
- When you change the layout engine, update `docs/PLACEMENT.md` (and CLAUDE.md if needed) in
  the same change. Tests/demos were removed earlier; verify by build + reading the PNG.

**CLI:** `build | validate | status | add-person | set | add-marriage | add-descent` (the last
takes `--depth N` or `--with FIGURE`). Edits are comment-preserving.

**Likely next:** more Shiji lineages as David reads — the 漢 本紀, the 世家 諸侯 states
(齊/晉/楚/趙/魏/韓/燕/宋/衛/陳/…), etc. **Known partials:** full rule 7 (multiple co-mothers under
one fatherless anchor); the chart is very tall (54 gens) — a more compact layout for long
single-child chains is a possible future enhancement, not yet needed.

Start by running `python3 -m familytree status`, reading `build/family_tree.png`, then ask
David for the next batch.

---
