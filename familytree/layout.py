"""Layout engine: genealogy DATA -> (x, y) for every tile.

Approach (modular so individual rules can be tweaked):
  * A tidy-tree pass (Reingold-Tilford family) packs sibling subtrees as close
    as possible while keeping a minimum gap at every shared generation row
    (rules 1-5). It is implemented with explicit left/right CONTOURS keyed by
    absolute generation, so it also handles a forest of multiple roots.
  * Genealogy extensions: a father reserves space to his (canonical) right for
    his wife tiles, which become a single composite block for sibling-packing
    (rule 6); mothers/spouses/descendant-only people inherit their anchor's row
    (rules 7-8).
  * Everything is computed in ONE canonical left-to-right orientation; if
    orientation is rtl we mirror all x at the very end (glyphs stay upright),
    putting the senior person on the RIGHT and oldest child rightmost.

Primary-placement precedence (each person placed exactly once):
  married-in spouse (wife-tile) -> under father -> under mother -> root.
Leftover links (married-in daughter -> father, descended-of) are emitted as
dashed SECONDARY edges.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .model import Dataset, Index, build_index


@dataclass
class Tile:
    id: str
    name: str
    x: float        # center x (final coords)
    top: float      # top y
    width: float
    height: float
    gen: int
    color: Optional[str] = None


@dataclass
class Block:
    """A laid-out subtree in a local canonical frame (its head node at x=0)."""
    x: Dict[str, float]          # id -> x
    left: Dict[int, float]       # generation -> leftmost tile edge
    right: Dict[int, float]      # generation -> rightmost tile edge


@dataclass
class LayoutResult:
    tiles: Dict[str, Tile]
    families: List[Tuple[str, List[str]]]   # parent -> child ids (lineage busbars)
    marriages: List[Tuple[str, str]]        # tiles to tie with a marriage line
    secondary: List[Tuple[str, str, str]]   # (from, to, kind) dashed edges
    width: float
    height: float
    roots: List[str]
    unplaced: List[str]
    sibling_groups: List[List[str]] = field(default_factory=list)   # parentless sib busbars


def _shift_block(b: Block, dx: float) -> None:
    if dx == 0:
        return
    for k in b.x:
        b.x[k] += dx
    for g in b.left:
        b.left[g] += dx
    for g in b.right:
        b.right[g] += dx


def _pack(blocks: List[Block], min_gap: float) -> Tuple[List[float], Dict[int, float], Dict[int, float]]:
    """Place blocks left-to-right, each as close as possible to the merged
    contour of all earlier blocks while keeping min_gap at every shared gen."""
    merged_left: Dict[int, float] = {}
    merged_right: Dict[int, float] = {}
    offsets: List[float] = []
    for i, b in enumerate(blocks):
        if i == 0:
            o = 0.0
        else:
            o = 0.0
            for g, le in b.left.items():
                if g in merged_right:
                    o = max(o, merged_right[g] + min_gap - le)
        offsets.append(o)
        for g in b.left:
            lo = b.left[g] + o
            ro = b.right[g] + o
            merged_left[g] = min(merged_left.get(g, lo), lo)
            merged_right[g] = max(merged_right.get(g, ro), ro)
    return offsets, merged_left, merged_right


def compute_layout(ds: Dataset, cfg: dict) -> LayoutResult:
    L = cfg["layout"]
    char_box = L["char_box"]
    pad = L["tile_pad"]
    tile_w = char_box + 2 * pad
    half = tile_w / 2.0
    h_gap = L["h_gap"]                      # standardized minimum horizontal gap (edge-to-edge)
    slot = tile_w + h_gap                    # husband-wife / wife-wife spacing == the sibling gap

    idx = build_index(ds)
    id_to = idx.id_to_person
    wife_persons = idx.wife_persons
    inlaw_sib_persons = idx.inlaw_sib_persons      # parentless in-law sibs: attached tiles, not nodes

    # wife tiles AND in-law sibling tiles are attached beside a host, never standalone nodes/roots
    attached = wife_persons | inlaw_sib_persons
    node_ids = [p.id for p in ds.people if p.id not in attached]
    node_set = set(node_ids)

    def parent_of(pid: str) -> Optional[str]:
        p = id_to[pid]
        if p.father_id and p.father_id in id_to and p.father_id not in wife_persons:
            return p.father_id
        if p.mother_id and p.mother_id in id_to and p.mother_id not in wife_persons:
            return p.mother_id
        return None

    # Build the placement forest: anchor -> children, plus roots.
    anchor_children: Dict[str, List[str]] = {}
    roots: List[str] = []
    for pid in node_ids:
        par = parent_of(pid)
        if par is None or par not in node_set:
            roots.append(pid)
        else:
            anchor_children.setdefault(par, []).append(pid)

    # A descended_from person is a phantom YOUNGEST child of the ancestor (the ancestor
    # centers over it; a SOLID line is drawn). Where it lands depends on the edge:
    #   depth: N        -> N generations below the ancestor (missing intermediates)  [rule 2]
    #   mentioned_with  -> on that person's row (still packed at the ancestor's child row) [rule X]
    #   neither         -> a plain direct youngest child                             [rule 1]
    descendant_render_ref: Dict[str, Optional[str]] = {}
    depth_offset: Dict[str, int] = {}
    phantom_order: Dict[str, int] = {}        # rank among an ancestor's phantom descendants
    for d in idx.descended:
        P, anc = d.person_id, d.ancestor_id
        if P in node_set and anc in node_set:
            if P in roots:
                roots.remove(P)
            anchor_children.setdefault(anc, []).append(P)
            if d.order is not None:
                phantom_order[P] = d.order
            if d.depth is not None and d.depth >= 1:
                depth_offset[P] = d.depth
            elif d.mentioned_with:
                descendant_render_ref[P] = d.mentioned_with

    def child_sort_key(cid: str):
        # real children sort by birth_order; phantom descendants (no birth_order) sort AFTER them,
        # among themselves by their explicit `order` (1 = senior/right), then name/id.
        c = id_to[cid]
        bo = c.birth_order if c.birth_order is not None else 10 ** 9
        return (bo, phantom_order.get(cid, 0), c.name, c.id)

    for k in anchor_children:
        anchor_children[k].sort(key=child_sort_key)

    # --- generations (rule 3) ---
    gen: Dict[str, int] = {}

    def assign_gen(root: str) -> None:
        stack = [(root, 0, frozenset())]
        while stack:
            pid, g, seen = stack.pop()
            if pid in seen:          # cycle guard
                continue
            gen[pid] = g
            seen2 = seen | {pid}
            for c in anchor_children.get(pid, []):
                stack.append((c, g + depth_offset.get(c, 1), seen2))

    for r in roots:
        assign_gen(r)

    # Rule X-c: a `mentioned_with` descendant renders on its referent's row — and so must
    # everything beneath it (its children one row below, etc.). assign_gen placed it a single
    # generation under its ancestor; re-base it AND its whole natal subtree onto the referent's
    # row so the subtree's depths stay correct (without this, a mentioned_with person with
    # children would sit deep while the children rendered shallow — a vertical split). Iterate
    # to a fixpoint so chained references settle (a descendant mentioned with a person who is
    # themselves re-based).
    if descendant_render_ref:
        order = sorted(descendant_render_ref, key=lambda p: gen.get(p, 0))
        for _ in range(len(descendant_render_ref) + 1):
            changed = False
            for P in order:
                ref = descendant_render_ref[P]
                if P in gen and ref in gen and gen[P] != gen[ref]:
                    delta = gen[ref] - gen[P]
                    stack, seen = [P], set()
                    while stack:
                        n = stack.pop()
                        if n in seen:
                            continue
                        seen.add(n)
                        gen[n] += delta
                        stack.extend(anchor_children.get(n, []))
                    changed = True
            if not changed:
                break

    # In-law family (rule L): a ROOT whose daughter married into the tree (she is a wife-tile
    # beside her husband) would otherwise sit at row 0, scattering her parents/siblings to the
    # top of the chart with a full-height connector. Hang the root ONE row above the daughter's
    # marriage row instead, and shift its whole natal subtree by the same delta, so her natal
    # family (parents + siblings) lands beside her. (Single married-in daughter per root;
    # multiple would over-constrain — not yet needed.) X-anchoring happens after layout, below.
    inlaw_roots: Dict[str, str] = {}      # in-law root id -> its married-in daughter id
    for r in list(roots):
        for p in ds.people:
            if p.id in wife_persons and r in (p.father_id, p.mother_id):
                h = idx.husband_of.get(p.id)
                if h is not None and h in gen:
                    inlaw_roots[r] = p.id
                    delta = (gen[h] - 1) - gen.get(r, 0)
                    if delta:
                        stack, seen = [r], set()
                        while stack:
                            n = stack.pop()
                            if n in seen:
                                continue
                            seen.add(n)
                            gen[n] += delta
                            stack.extend(anchor_children.get(n, []))
                    break

    secondary: List[Tuple[str, str, str]] = []

    # wife tiles share the husband's row (rules 6-7)
    for w in wife_persons:
        h = idx.husband_of.get(w)
        if h is not None and h in gen:
            gen[w] = gen[h]

    # in-law sibling tiles share their host's row (rule Sib)
    for sib, host in idx.sib_host.items():
        if host in gen:
            gen[sib] = gen[host]

    # Note 3: a descendant-only person is RENDERED on the row of the person it was
    # mentioned with (its x already comes from being a phantom child of the ancestor).
    render_gen = dict(gen)
    for P, ref in descendant_render_ref.items():
        if ref and ref in gen:
            render_gen[P] = gen[ref]

    # A spouse-tile who is also a child/descendant of someone in the chart becomes an EXTRA
    # busbar child of that ancestor: the ancestor centers over her too and a SOLID orthogonal
    # lineage line runs to her (no dashed edges). She still sits beside her partner.
    extra_busbar: Dict[str, List[str]] = {}
    for p in ds.people:
        if p.id in wife_persons and p.father_id and p.father_id in id_to:
            extra_busbar.setdefault(p.father_id, []).append(p.id)
    for d in idx.descended:
        if d.person_id in wife_persons and d.ancestor_id in id_to:
            extra_busbar.setdefault(d.ancestor_id, []).append(d.person_id)

    # --- x via tidy layout (canonical, left-to-right) ---
    def place_wives(nid: str, X: Dict[str, float], base_x: float) -> float:
        """Add this node's wife tiles to its right (canonical). Return right edge."""
        right = base_x + half
        j = 0
        for w in idx.wives_of.get(nid, []):
            if w not in id_to:
                continue
            j += 1
            X[w] = base_x + j * slot
            right = X[w] + half
        return right

    def place_husbands(nid: str, X: Dict[str, float], base_x: float) -> float:
        """Add free-root husband tiles to this node's left (canonical) -> right after mirror.
        Keeps wife-left/husband-right. Return left edge."""
        left = base_x - half
        j = 0
        for h in idx.husbands_of.get(nid, []):
            if h not in id_to:
                continue
            j += 1
            X[h] = base_x - j * slot
            left = X[h] - half
        return left

    def place_inlaw_sibs(nid: str, X: Dict[str, float], base_x: float) -> float:
        """Attach parentless in-law sibling tiles to this node's left (canonical) -> right after
        the mirror, past any husband tiles — so an ELDER in-law sib sits on the senior (right)
        side, beyond the host (rule Sib). e.g. 周呂侯 lands just right of 漢高祖. Return left edge."""
        j = sum(1 for h in idx.husbands_of.get(nid, []) if h in id_to)
        left = base_x - half
        for s in idx.inlaw_sib_of.get(nid, []):
            if s not in id_to:
                continue
            j += 1
            X[s] = base_x - j * slot
            left = X[s] - half
        return left

    visiting: Set[str] = set()

    def layout_block(nid: str) -> Block:
        g = gen.get(nid, 0)
        if nid in visiting:                      # cycle guard
            return Block({nid: 0.0}, {g: -half}, {g: half})
        visiting.add(nid)
        kids = anchor_children.get(nid, [])
        if not kids:
            X = {nid: 0.0}
            wright = place_wives(nid, X, 0.0)
            hleft = place_husbands(nid, X, 0.0)
            sleft = place_inlaw_sibs(nid, X, 0.0)
            visiting.discard(nid)
            return Block(X, {g: min(-half, hleft, sleft)}, {g: max(half, wright)})

        blocks = [layout_block(c) for c in kids]
        for c, b in zip(kids, blocks):
            _shift_block(b, -b.x[c])             # normalize child head to 0
        # A `mentioned_with` phantom renders on a deep row, but it is still a youngest CHILD of
        # nid: reserve a slot at nid's child-row so it spaces beside nid's real children (rule X
        # — it sits to their left) instead of sliding up underneath one of them.
        child_row = g + 1
        for c, b in zip(kids, blocks):
            if c in descendant_render_ref:
                b.left[child_row] = min(b.left.get(child_row, half), -half)
                b.right[child_row] = max(b.right.get(child_row, -half), half)
        offsets, mL, mR = _pack(blocks, h_gap)
        node_x = (offsets[0] + offsets[-1]) / 2.0  # center over first..last child (rule 4)

        X = {nid: 0.0}
        for c, b, o in zip(kids, blocks, offsets):
            for pid, px in b.x.items():
                X[pid] = px + o - node_x
        Lc = {gg: v - node_x for gg, v in mL.items()}
        Rc = {gg: v - node_x for gg, v in mR.items()}

        wright = place_wives(nid, X, 0.0)
        hleft = place_husbands(nid, X, 0.0)
        sleft = place_inlaw_sibs(nid, X, 0.0)
        Lc[g] = min(Lc.get(g, -half), -half, hleft, sleft)
        Rc[g] = max(Rc.get(g, half), max(half, wright))

        # Long descent (rule X-c with a deep subtree, e.g. 劉累 → the 漢 line ~40 rows below):
        # the connecting busbar runs through many EMPTY intermediate rows. Reserve its x-lane on
        # those rows so a neighbouring column (e.g. 周) cannot slide underneath the line and cross
        # it. The tidy-tree packer then keeps the lane clear with the minimal shift and re-centers
        # the ancestors automatically (no manual coordinates).
        if nid in descendant_render_ref:
            cgs = [gen.get(c, g) for c in kids]
            if cgs and min(cgs) - g > 1:
                xs = [X[c] for c in kids if c in X]
                lo, hi = min(xs) - half, max(xs) + half
                for gg in range(g + 1, min(cgs)):    # reserve the descent's full x-span
                    Lc[gg] = min(Lc.get(gg, lo), lo)
                    Rc[gg] = max(Rc.get(gg, hi), hi)
        visiting.discard(nid)
        return Block(X, Lc, Rc)

    root_blocks: List[Block] = []
    block_members: Dict[str, Set[str]] = {}
    for r in roots:
        b = layout_block(r)
        _shift_block(b, -b.x[r])
        root_blocks.append(b)
        block_members[r] = set(b.x)

    final_x: Dict[str, float] = {}
    if root_blocks:
        offsets, _, _ = _pack(root_blocks, h_gap)
        for r, b, o in zip(roots, root_blocks, offsets):
            for pid, px in b.x.items():
                final_x[pid] = px + o

    # An ancestor centers over its busbar children INCLUDING extras (spouse children whose
    # own x is fixed by their marriage). Safe for roots; a non-root would ideally re-center
    # its parent too (not needed yet — see docs/PLACEMENT.md known limitations).
    for anc, extras in extra_busbar.items():
        if anc in inlaw_roots:        # in-law roots are X-anchored below, not here
            continue
        kids = list(anchor_children.get(anc, [])) + extras
        xs = [final_x[k] for k in kids if k in final_x]
        if xs and anc in final_x:
            final_x[anc] = (min(xs) + max(xs)) / 2.0

    # Rule L (X-anchoring): an in-law root sits at row 0's left after packing — far from its
    # married-in daughter. The daughter's marriage row is the densest in the chart (her co-wives
    # and in-laws fill it), so there is no adjacent slot. Park the natal block just past the
    # right edge of that row (clear of the cluster, on the rows fixed in Part 1), then center the
    # root over [its real children + the daughter] so the busbar reaches her, and slide the
    # root's wife along with it so she stays beside him.
    for r, daughter in inlaw_roots.items():
        if r not in final_x or daughter not in final_x:
            continue
        members = block_members.get(r, {r})
        drow = render_gen.get(daughter, gen.get(daughter))
        row_xs = [final_x[t] for t in final_x
                  if t not in members and render_gen.get(t, gen.get(t)) == drow]
        edge = max(row_xs) if row_xs else final_x[daughter]
        real_kids = [k for k in anchor_children.get(r, []) if k in final_x]
        anchor = real_kids[0] if real_kids else r
        shift = (edge + slot) - final_x[anchor]
        for m in members:
            final_x[m] += shift
        kids_x = [final_x[k] for k in real_kids] + [final_x[daughter]]
        drift = (min(kids_x) + max(kids_x)) / 2.0 - final_x[r]
        final_x[r] += drift
        for w in idx.wives_of.get(r, []):
            if w in final_x:
                final_x[w] += drift

    # Free (disconnected) components — roots not joined to the main tree by ANY edge
    # (parent, marriage, or descent) — can sit anywhere, so move them clear of the main
    # tree (off to one side; they keep their own top rows) so they never overlap it.
    adj: Dict[str, Set[str]] = {p.id: set() for p in ds.people}

    def _link(a, b):
        if a in adj and b in adj:
            adj[a].add(b)
            adj[b].add(a)

    for p in ds.people:
        _link(p.id, p.father_id)
        _link(p.id, p.mother_id)
    for m in ds.marriages:
        _link(m.husband_id, m.wife_id)
    for d in ds.descended_from:
        _link(d.person_id, d.ancestor_id)
    for grp in idx.sibling_groups:               # parentless sibs are joined to each other
        for s in grp[1:]:
            _link(grp[0], s)
    seen_c: Set[str] = set()
    comps: List[Set[str]] = []
    for pid in adj:
        if pid in seen_c:
            continue
        comp: Set[str] = set()
        stack = [pid]
        while stack:
            x = stack.pop()
            if x in seen_c:
                continue
            seen_c.add(x)
            comp.add(x)
            stack.extend(adj[x] - seen_c)
        comps.append(comp)
    if len(comps) > 1:
        main_comp = max(comps, key=len)
        free_ids = [pid for pid in final_x if pid not in main_comp]
        main_ids = [pid for pid in final_x if pid in main_comp]
        if free_ids and main_ids:
            shift = min(final_x[p] for p in main_ids) - max(final_x[p] for p in free_ids) - (tile_w + 3 * h_gap)
            for p in free_ids:
                final_x[p] += shift

    # --- single horizontal mirror for rtl (glyphs stay upright) ---
    if cfg.get("orientation", "rtl") == "rtl":
        for k in list(final_x):
            final_x[k] = -final_x[k]

    # --- generations -> rows; pin min gen to 0 ---
    gmin = min(gen.values()) if gen else 0

    # Uniform tile height: tall enough for the longest name in the dataset, so
    # every tile is the same size regardless of its own name length.
    max_chars = max((len(p.name) for p in ds.people), default=1)
    tile_height = max(max_chars, 1) * char_box + 2 * pad
    generation_gap = tile_height + L["v_gap"]
    margin = L["margin"]

    min_left = min((final_x[k] - half for k in final_x), default=0.0)
    dx = margin - min_left

    tiles: Dict[str, Tile] = {}
    for pid in final_x:
        g = render_gen.get(pid, gen.get(pid, 0)) - gmin
        tiles[pid] = Tile(
            id=pid, name=id_to[pid].name,
            x=final_x[pid] + dx,
            top=margin + g * generation_gap,
            width=tile_w, height=tile_height, gen=g,
            color=id_to[pid].color,
        )

    width = max((t.x + t.width / 2 for t in tiles.values()), default=margin) + margin
    height = max((t.top + t.height for t in tiles.values()), default=margin) + margin

    families = []
    for f in list(anchor_children) + [a for a in extra_busbar if a not in anchor_children]:
        kids = [k for k in (list(anchor_children.get(f, [])) + extra_busbar.get(f, [])) if k in tiles]
        if f in tiles and kids:
            families.append((f, kids))

    marriages: List[Tuple[str, str]] = []
    for h, wives in idx.wives_of.items():
        prev = h
        for w in wives:
            if prev in tiles and w in tiles:
                marriages.append((prev, w))
            prev = w
    for host, husbands in idx.husbands_of.items():       # right-side (free-root) husband tiles
        for hb in husbands:
            if host in tiles and hb in tiles:
                marriages.append((host, hb))

    secondary = [(a, b, k) for (a, b, k) in secondary if a in tiles and b in tiles]
    unplaced = [p.id for p in ds.people if p.id not in tiles]

    sib_groups = [[m for m in g if m in tiles] for g in idx.sibling_groups]
    sib_groups = [g for g in sib_groups if len(g) >= 2]

    return LayoutResult(tiles, families, marriages, secondary, width, height, roots, unplaced,
                        sib_groups)
