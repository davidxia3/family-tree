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
    married_out: List[Tuple[str, str]] = field(default_factory=list)  # (father, married-out daughter), rule MO


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
    flip_husband_ids = {h for hs in idx.husbands_of.values() for h in hs}  # married-out-daughter husbands (rule D2)

    # wife tiles AND in-law sibling tiles are attached beside a host, never standalone nodes/roots
    attached = wife_persons | inlaw_sib_persons
    node_ids = [p.id for p in ds.people if p.id not in attached]
    node_set = set(node_ids)

    # A flip-husband (rule D2) is an attached tile too, but unlike a plain wife he may be a PARENT
    # — his children descend from him (beside his wife). So he is allowed as a parent here, and his
    # children are anchored under him (and carried along when he is placed), not orphaned.
    def parent_of(pid: str) -> Optional[str]:
        p = id_to[pid]
        if p.father_id and p.father_id in id_to and (p.father_id not in wife_persons or p.father_id in flip_husband_ids):
            return p.father_id
        if p.mother_id and p.mother_id in id_to and p.mother_id not in wife_persons:
            return p.mother_id
        return None

    # Build the placement forest: anchor -> children, plus roots. A child whose parent is an
    # attached tile that can carry a subtree (an in-law sibling, rule Sib; or a flip-husband, rule
    # D2) is still anchored under that parent — its subtree is laid out and carried along when the
    # parent is placed, NOT orphaned into a root.
    carriers = inlaw_sib_persons | flip_husband_ids
    anchor_children: Dict[str, List[str]] = {}
    roots: List[str] = []
    for pid in node_ids:
        par = parent_of(pid)
        if par is None or (par not in node_set and par not in carriers):
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

    # in-law sibling tiles share their host's row (rule Sib); their own subtrees (an in-law sib
    # may have children, e.g. 呂悼武王 → 呂肅王 …) descend from there — assign those rows too,
    # since the sib is not a root and was skipped by assign_gen. Do this BEFORE the wife override
    # so a spouse married into one of those subtrees (e.g. 瑯邪王劉澤 ← 瑯邪后) gets a real row.
    for sib, host in idx.sib_host.items():
        if host in gen:
            gen[sib] = gen[host]
            stack = [sib]
            seen2: Set[str] = set()
            while stack:
                n = stack.pop()
                if n in seen2:
                    continue
                seen2.add(n)
                for c in anchor_children.get(n, []):
                    gen[c] = gen[n] + depth_offset.get(c, 1)
                    stack.append(c)

    # wife tiles share the husband's row (rules 6-7)
    for w in wife_persons:
        h = idx.husband_of.get(w)
        if h is not None and h in gen:
            gen[w] = gen[h]

    # a flip-husband (rule D2) now sits on his wife's row (set just above); his own children
    # descend from him — assign those rows too (he was skipped by assign_gen, like an in-law sib).
    for fh in flip_husband_ids:
        if fh in gen:
            stack = [fh]
            seen3: Set[str] = set()
            while stack:
                n = stack.pop()
                if n in seen3:
                    continue
                seen3.add(n)
                for c in anchor_children.get(n, []):
                    gen[c] = gen[n] + depth_offset.get(c, 1)
                    stack.append(c)

    # Note 3: a descendant-only person is RENDERED on the row of the person it was
    # mentioned with (its x already comes from being a phantom child of the ancestor).
    render_gen = dict(gen)
    for P, ref in descendant_render_ref.items():
        if ref and ref in gen:
            render_gen[P] = gen[ref]

    # A spouse-descendant (a wife-tile who is also a `descended_from` descendant) is an EXTRA busbar
    # child of that ancestor: the ancestor centers over her and a solid line runs to her (e.g. 女華).
    #
    # But a daughter who married OUT — a wife-tile whose own FATHER is in the tree, so she sits
    # beside her husband in HIS family's part of the chart — does NOT count for her father's
    # centering and is NOT on his main busbar (rule MO). The father stays centered over the children
    # who remain in his family; she gets a SEPARATE connector (rendered "up and over"). e.g.
    # 孝惠皇后 ← 宣平侯張敖 (she married her uncle 漢孝惠帝).
    extra_busbar: Dict[str, List[str]] = {}
    married_out: Dict[str, List[str]] = {}
    for p in ds.people:
        if p.id in wife_persons and p.father_id and p.father_id in id_to:
            married_out.setdefault(p.father_id, []).append(p.id)
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
        """Add married-out-daughter husband tiles to this node's left (canonical) -> right after
        the mirror. Keeps wife-left/husband-right (rule D2). A husband with his OWN children (e.g.
        宣平侯張敖) carries his whole subtree, laid out as a block beside the wife. Return left edge."""
        left = base_x - half
        cursor = base_x - half
        for h in idx.husbands_of.get(nid, []):
            if h not in id_to:
                continue
            if anchor_children.get(h):              # husband has a subtree -> lay it out and carry it
                b = layout_block(h)
                _shift_block(b, -b.x[h])             # husband head at 0
                br = max(b.right.values()) if b.right else half
                bl = min(b.left.values()) if b.left else -half
                head = cursor - h_gap - br
                for pid, px in b.x.items():
                    X[pid] = px + head
                cursor = head + bl
            else:
                head = cursor - h_gap - half
                X[h] = head
                cursor = head - half
            left = min(left, cursor)
        return left

    def place_inlaw_sibs(nid: str, X: Dict[str, float], base_x: float, start_left: float) -> float:
        """Attach parentless in-law sibling tiles to this node's left (canonical) -> right after
        the mirror — so an ELDER in-law sib sits on the senior (right) side, beyond the host (rule
        Sib). An in-law sib that has its OWN children carries its whole subtree (laid out as a
        block, packed edge-to-edge with its neighbours). `start_left` is the host block's current
        left extent, so the sibs (and their deep subtrees) are parked CLEAR of the host's own
        children rather than overlapping them. Return left edge.

        NOTE (first pass / known-rough): this clears overlaps but leaves the in-law family parked
        off to the side of the host instead of tidily nested — positions still need correction."""
        cursor = start_left                          # grow leftward (canonical) from the block's left edge
        left = start_left
        for s in idx.inlaw_sib_of.get(nid, []):
            if s not in id_to:
                continue
            if anchor_children.get(s):              # sib has a subtree -> lay it out and carry it
                b = layout_block(s)
                _shift_block(b, -b.x[s])             # sib head at 0
                br = max(b.right.values()) if b.right else half
                bl = min(b.left.values()) if b.left else -half
                head = cursor - h_gap - br
                for pid, px in b.x.items():
                    X[pid] = px + head
                cursor = head + bl
            else:
                head = cursor - h_gap - half
                X[s] = head
                cursor = head - half
            left = min(left, cursor)
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
            sleft = place_inlaw_sibs(nid, X, 0.0, min(-half, hleft))
            visiting.discard(nid)
            # contour from ALL placed tiles (so a carried husband/sib subtree at deeper rows is
            # accounted for in sibling packing — otherwise it would overlap a neighbour's subtree)
            Lc, Rc = {}, {}
            for pid, px in X.items():
                gg = gen.get(pid, g)
                Lc[gg] = min(Lc.get(gg, px - half), px - half)
                Rc[gg] = max(Rc.get(gg, px + half), px + half)
            Lc[g] = min(Lc.get(g, -half), -half, hleft, sleft)
            Rc[g] = max(Rc.get(g, half), half, wright)
            return Block(X, Lc, Rc)

        blocks = [layout_block(c) for c in kids]
        for c, b in zip(kids, blocks):
            _shift_block(b, -b.x[c])             # normalize child head to 0
        # A phantom descendant (`mentioned_with` OR `depth: N`) renders on a deeper row, but it is
        # still a youngest CHILD of nid: reserve a slot at nid's child-row so it spaces beside nid's
        # real children (rule X — to their left, ordered after them) instead of sliding up
        # underneath one of them. e.g. 隆慮侯蟜 (景帝's grandson, depth 2) sits left of 景帝's sons'
        # subtrees and drops straight from 景帝, not from a tile two rows up (王夫人).
        child_row = g + 1
        for c, b in zip(kids, blocks):
            if c in descendant_render_ref or c in depth_offset:
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
        # park in-law sibs (and their subtrees) past the host's whole left extent, so they clear
        # the host's own children (which are centered under the host and span both sides)
        start_left = min([v for v in Lc.values()] + [-half, hleft])
        sleft = place_inlaw_sibs(nid, X, 0.0, start_left)
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

    # --- manual layer ordering (rule LO): pin each listed row in the given LEFT-TO-RIGHT order.
    # Each listed tile carries its WHOLE subtree (descendants + their attached spouse/sib tiles,
    # stopping at any other listed tile); those subtree-blocks are contour-packed in the given
    # order so they never overlap (spread out, no line collisions), then shifted so the listed
    # tile with the largest subtree stays where it was (the rest of the chart doesn't move). ---
    def _block_of(t: str, pinned: Set[str]) -> Set[str]:
        members: Set[str] = set()
        stack = [t]
        while stack:
            n = stack.pop()
            if n in members:
                continue
            members.add(n)
            for c in anchor_children.get(n, []):
                if c not in pinned:
                    stack.append(c)
            for a in (idx.wives_of.get(n, []) + idx.husbands_of.get(n, []) + idx.inlaw_sib_of.get(n, [])):
                if a not in pinned and a in final_x:
                    stack.append(a)
        return {m for m in members if m in final_x}

    def _row(m: str) -> int:
        return render_gen.get(m, gen.get(m, 0))

    for order_list in ds.layer_order:
        present = [i for i in order_list if i in final_x]
        if len(present) < 2:
            continue
        pinned = set(present)
        # A listed WIFE is not packed as her own block — she rides immediately beside her husband
        # (rule W) INSIDE his block, so a wide husband subtree can never shove the wife away from
        # him (e.g. 呂太后 stays next to 漢高祖 instead of being stranded over his leftmost child).
        # A sibling of one of his wives listed DIRECTLY beside the wife block rides along too, just
        # outside the wives (e.g. 薄昭, 薄后's brother, sits immediately left of 戚夫人) — so wife-kin
        # hug the wives rather than being stranded out in the row's auto-packed run.
        sib_group: Dict[str, Set[str]] = {}
        for g in idx.sibling_groups:
            for m in g:
                sib_group[m] = set(g)
        carried: Dict[str, List[str]] = {}              # husband -> his listed wives (+ wife-kin)
        wife_carried: Set[str] = set()
        for h in present:
            ws = [w for w in idx.wives_of.get(h, []) if w in pinned]
            if not ws:
                continue
            wifeset = set(ws)
            sibs: List[str] = []
            for w in ws:                                # a wife-sibling listed next to a wife
                i = present.index(w)
                for j in (i - 1, i + 1):
                    if 0 <= j < len(present):
                        t = present[j]
                        if t not in wifeset and t != h and t not in sibs \
                                and any(t in sib_group.get(wf, ()) for wf in ws):
                            sibs.append(t)
            carried[h] = ws + sibs
            wife_carried.update(ws)
            wife_carried.update(sibs)
            if sibs:                                    # park wife-kin just left of the leftmost wife
                lw = min(final_x[w] for w in ws)
                for k, t in enumerate(sorted(sibs, key=present.index, reverse=True), start=1):
                    final_x[t] = lw - k * slot
        order = [t for t in present if t not in wife_carried]
        blocks: List[Block] = []
        memsets: List[Set[str]] = []
        for t in order:
            mem = _block_of(t, (pinned - {t}) - set(carried.get(t, [])))  # husband keeps his wives
            mem |= set(carried.get(t, []))             # +wife-kin parked beside the wives
            memsets.append(mem)
            head = final_x[t]
            bx = {m: final_x[m] - head for m in mem}
            bl: Dict[int, float] = {}
            br: Dict[int, float] = {}
            for m, x in bx.items():
                gg = _row(m)
                bl[gg] = min(bl.get(gg, x - half), x - half)
                br[gg] = max(br.get(gg, x + half), x + half)
            blocks.append(Block(bx, bl, br))
        offsets, _, _ = _pack(blocks, h_gap)
        ai = max(range(len(order)), key=lambda i: len(memsets[i]))  # anchor = largest subtree
        shift = final_x[order[ai]] - offsets[ai]
        for t, mem, off in zip(order, memsets, offsets):
            delta = (off + shift) - final_x[t]
            if delta:
                for m in mem:
                    final_x[m] += delta

    # A PARTIAL layer_order can WIDEN its cluster into a neighbouring auto-placed subtree (the 王
    # 外戚 row bumping 趙幽王's son 趙王劉遂). The cluster is anchored on one tile and grows to the
    # OTHER side; push every non-pinned family on that side OUTWARD by the overhang, as one rigid
    # group (so they clear the cluster without interleaving with each other). Pinned tiles never move.
    pinned_all: Set[str] = set()
    for grp in ds.layer_order:
        pinned_all.update(grp)

    def _free_root(t: str) -> str:                     # highest non-pinned ancestor (its family head)
        r = t
        while True:
            par = parent_of(r)
            if par is None or par in pinned_all or par not in final_x:
                return r
            r = par

    def _descendants(t: str) -> Set[str]:              # all placed descendants of t (any depth)
        out: Set[str] = set()
        stack = list(anchor_children.get(t, []))
        while stack:
            n = stack.pop()
            if n in out or n not in final_x:
                continue
            out.add(n)
            stack.extend(anchor_children.get(n, []))
        return out

    for grp in ds.layer_order:
        present = [t for t in grp if t in final_x]
        if len(present) < 2:
            continue
        cl = min(final_x[t] for t in present)
        cr = max(final_x[t] for t in present)
        rows_c = {render_gen.get(t, gen.get(t, 0)) for t in present}
        cluster = set()                                 # the cluster's own tiles + their subtrees
        for t in present:
            cluster |= _block_of(t, set(present) - {t})
        # how far do NEIGHBOURING (non-cluster) tiles intrude into the cluster from each side?
        over_l, cut_l, over_r, cut_r = 0.0, cl, 0.0, cr
        for p, x in final_x.items():
            if p in pinned_all or p in cluster or render_gen.get(p, gen.get(p, 0)) not in rows_c:
                continue
            if cl - tile_w < x <= (cl + cr) / 2:        # intrudes from the left half
                d = x + tile_w + h_gap - cl
                if d > over_l:
                    over_l, cut_l = d, final_x[_free_root(p)]
            elif (cl + cr) / 2 < x < cr + tile_w:       # intrudes from the right half
                d = cr + tile_w + h_gap - x
                if d > over_r:
                    over_r, cut_r = d, final_x[_free_root(p)]
        for over, cut, sign in ((over_l, cut_l, -1.0), (over_r, cut_r, 1.0)):
            if over <= 0.5:
                continue
            on_side = (lambda x: x <= cut) if sign < 0 else (lambda x: x >= cut)
            to_move = {p for p in final_x if p not in pinned_all and p not in cluster
                       and on_side(final_x[_free_root(p)])}
            # A pinned tile sitting on the shifting side rides along with it, so it keeps its
            # centering and row-gaps (e.g. the whole 劉賈/楚元王/呂… left run moves as one). A pinned
            # tile with a SPLIT subtree — some children move, some don't (漢高祖, who anchors the
            # cluster from the right) — must stay put, so exclude it.
            for pt in pinned_all:
                if pt in final_x and pt not in to_move and on_side(final_x[pt]) \
                        and _descendants(pt) <= to_move:
                    to_move.add(pt)
            for p in to_move:
                final_x[p] += sign * over

    # --- re-center fathers over their (re-packed) children, bottom-up. A layer_order re-orders a
    # row but does NOT move the father one row above it, leaving him stale (e.g. 漢太上皇 over
    # 楚元王/漢高祖/代頃王). Walk deepest-row-first so a parent is centered after its children settle,
    # and the correction propagates up. Children = the busbar set (anchor + spouse-descendants;
    # married-out daughters already excluded, rule MO). Skip pinned tiles and descent ANCESTORS,
    # whose cross-chart placement (lane reservation, rule X — e.g. the 帝堯→劉累 shift) is deliberate.
    descent_anchors = {d.ancestor_id for d in idx.descended}

    def _under_pinned(t: str) -> bool:                  # inside a pinned LO block (rigid, already centered)
        r, seen = parent_of(t), set()
        while r is not None and r not in seen:
            if r in pinned_all:
                return True
            seen.add(r)
            r = parent_of(r)
        return False

    recenter = sorted((p for p in final_x if p not in pinned_all and p not in descent_anchors
                       and not _under_pinned(p)),
                      key=lambda p: render_gen.get(p, gen.get(p, 0)), reverse=True)
    for p in recenter:
        ks = [c for c in (anchor_children.get(p, []) + extra_busbar.get(p, [])) if c in final_x]
        if ks:
            xs = [final_x[c] for c in ks]
            delta = (min(xs) + max(xs)) / 2.0 - final_x[p]
            final_x[p] += delta
            for w in idx.wives_of.get(p, []):       # the father's wives ride along, staying beside him
                if w in final_x:
                    final_x[w] += delta

    # A CHILDLESS child can be left stranded with slack in the wiggle-room over its junior sibling's
    # deep subtree. Tuck it tight against its SENIOR sibling and slide that senior side in to close
    # the float — its drop then just clears the junior subtree instead of crossing it. e.g. 趙隱王
    # (between 漢孝文帝's tall line and 魯元公主) is pinned immediately left of 魯元公主, and the
    # 魯元公主/漢孝惠帝/齊悼惠王 group slides left against 漢孝文帝's subtree. The slide is capped by the
    # per-row contour gap to everything on the junior side, so it can never cause an overlap.
    def _contour(tiles: Set[str], pick) -> Dict[int, float]:
        out: Dict[int, float] = {}
        for m in tiles:
            r = render_gen.get(m, gen.get(m, 0))
            out[r] = pick(out[r], final_x[m]) if r in out else final_x[m]
        return out

    tuck_parents: Set[str] = set()
    for par, kids in list(anchor_children.items()):
        ks = sorted((k for k in kids if k in final_x), key=lambda k: final_x[k])
        def _maxrow(blk: Set[str]) -> int:
            return max((render_gen.get(m, gen.get(m, 0)) for m in blk), default=0)

        for i in range(1, len(ks) - 1):
            c = ks[i]
            if _descendants(c):                         # only a truly childless tile floats like this
                continue
            jun, sen = ks[i - 1], ks[i + 1]
            jblk, sblk = _block_of(jun, set()), _block_of(sen, set())
            # only when c floats over a DEEPER junior subtree than the senior's — then it belongs
            # tucked against the shallow senior, not stranded over the deep junior (e.g. 趙隱王: 漢孝文帝
            # runs to row 58, 魯元公主 only to row 56). Otherwise leave the auto packing alone.
            if _maxrow(jblk) <= _maxrow(sblk):
                continue
            # Rule H: the junior subtree's CONTOUR is its tiles per row, not its bounding box. c only
            # has to clear the junior at ITS OWN row (it nests above the deeper rows), so measure the
            # junior's right edge AT c's row — not its widest extent. This lets c (and the senior side)
            # nest tight against the overhang instead of clearing the whole subtree.
            crow = render_gen.get(c, gen.get(c, 0))
            jbound = max((final_x[m] for m in jblk if render_gen.get(m, gen.get(m, 0)) == crow),
                         default=final_x[jun])
            want = final_x[sen] - (jbound + 2 * slot)   # slide so c lands one gap left of the senior
            if want <= 0.5:                             # already tight — nothing to close
                continue
            senior = set().union(*(_block_of(k, set()) for k in ks[i + 1:]))
            # the senior side (and c) must clear EVERY tile to their left per row — not just the junior
            # subtree — so sliding them in can never collide with an unrelated line.
            others: Dict[int, List[float]] = {}
            for n2, x2 in final_x.items():
                if n2 in senior or n2 == c:
                    continue
                r2 = render_gen.get(n2, gen.get(n2, 0))
                others.setdefault(r2, []).append(x2)
            room = want
            for t in senior:
                r2 = render_gen.get(t, gen.get(t, 0))
                lefts = [x for x in others.get(r2, []) if x < final_x[t] - 1]
                if lefts:
                    room = min(room, final_x[t] - max(lefts) - slot)
            shift = max(0.0, min(want, room))           # never slide past anything on the left
            if shift <= 0.5:
                continue
            for t in senior:
                final_x[t] -= shift
            final_x[c] = final_x[sen] - slot            # c rides immediately left of the senior
            lefts = [x for x in others.get(crow, []) if x < final_x[c] - 1]
            if lefts and final_x[c] - max(lefts) < slot - 0.5:
                final_x[c] = max(lefts) + slot          # keep c clear of its own left neighbour
            tuck_parents.add(par)

    # The nesting moved children (e.g. 太伯/虞仲 in under 古公亶父), so re-center their parents and walk
    # up each chain. Every move is CLAMPED to stay one gap clear of the node's row-neighbours, so a
    # chain with side-children can never drift into them — the offset just stops where it would touch.
    def _recenter_clamped(p: str) -> None:
        if p in pinned_all or p in descent_anchors:
            return
        ks = [c for c in (anchor_children.get(p, []) + extra_busbar.get(p, [])) if c in final_x]
        if not ks:
            return
        kin = set(idx.wives_of.get(p, [])) | {p}
        prow = render_gen.get(p, gen.get(p, 0))
        rowx = [final_x[n] for n in final_x
                if n not in kin and render_gen.get(n, gen.get(n, 0)) == prow]
        cur = final_x[p]
        lo = max([x for x in rowx if x < cur - 1] or [-1e18]) + slot
        hi = min([x for x in rowx if x > cur + 1] or [1e18]) - slot
        xs = [final_x[c] for c in ks]
        new = max(lo, min((min(xs) + max(xs)) / 2.0, hi))
        delta = new - cur
        if abs(delta) > 0.5:
            for n in kin:
                if n in final_x:
                    final_x[n] += delta

    seen_rc: Set[str] = set()
    for p0 in sorted(tuck_parents, key=lambda p: render_gen.get(p, gen.get(p, 0)), reverse=True):
        p: Optional[str] = p0
        while p is not None and p not in seen_rc and not _under_pinned(p):
            seen_rc.add(p)
            _recenter_clamped(p)
            p = parent_of(p)

    # The layer_order packed the tiles on each side of its anchor BEFORE the tuck closed the anchor's
    # subtree, so the outer ones now sit too far out. Compact each tile beyond the anchor back toward
    # it (its whole subtree), per-row, cascading — closing one gap opens room for the next (e.g.
    # 建成侯呂釋之 slides in against 漢高祖's now-tightened brood, then 呂悼武王, then 代頃王).
    comp_parents: Set[str] = set()
    for order_list in ds.layer_order:
        present = [i for i in order_list if i in final_x]
        if len(present) < 2:
            continue
        pinned = set(present)
        anchor = max(present, key=lambda t: len(_block_of(t, pinned - {t})))
        ax = final_x[anchor]
        outer = sorted((t for t in present if abs(final_x[t] - ax) > 1),
                       key=lambda t: abs(final_x[t] - ax))   # nearest the anchor first
        for t in outer:
            blk = _block_of(t, pinned - {t})
            sign = 1.0 if final_x[t] > ax else -1.0          # right side pulls left, left side pulls right
            byrow_now: Dict[int, List[float]] = {}
            for n2, x2 in final_x.items():
                if n2 in blk:
                    continue
                r2 = render_gen.get(n2, gen.get(n2, 0))
                byrow_now.setdefault(r2, []).append(x2)
            slack = 1e18
            for m in blk:
                r2 = render_gen.get(m, gen.get(m, 0))
                near = [x for x in byrow_now.get(r2, []) if (x < final_x[m] - 1) == (sign > 0)]
                if near:
                    edge = max(near) if sign > 0 else min(near)
                    slack = min(slack, abs(final_x[m] - edge) - slot)
            if 0.5 < slack < 1e17:
                for m in blk:
                    final_x[m] -= sign * slack
                par = parent_of(t)
                if par is not None:
                    comp_parents.add(par)
    for p in comp_parents:
        _recenter_clamped(p)

    # --- generations -> rows; pin min gen to 0 ---
    gmin = min(gen.values()) if gen else 0

    # Uniform tile height: tall enough for the longest name in the dataset, so
    # every tile is the same size regardless of its own name length.
    max_chars = max((len(p.name) for p in ds.people), default=1)
    tile_height = max(max_chars, 1) * char_box + 2 * pad
    generation_gap = tile_height + L["v_gap"]
    margin = L["margin"]

    # --- grid snap: pin every tile to a tile-width column so it occupies exactly ONE grid cell, with
    # at least one empty column (= one tile width) between same-row neighbours. This is the basis for
    # the semi-manual model, where a tile's position is an integer (column, generation). ---
    col_w = tile_w
    by_row_snap: Dict[int, List[str]] = {}
    for pid in final_x:
        by_row_snap.setdefault(render_gen.get(pid, gen.get(pid, 0)), []).append(pid)
    for ids in by_row_snap.values():
        ids.sort(key=lambda p: final_x[p])
        prev_col: Optional[int] = None
        for p in ids:
            col = round(final_x[p] / col_w)
            if prev_col is not None and col < prev_col + 2:    # 1 tile-cell + 1 gap-cell
                col = prev_col + 2
            final_x[p] = col * col_w
            prev_col = col

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

    married_out_links: List[Tuple[str, str]] = []       # (father, married-out daughter) — rule MO
    for f, daughters in married_out.items():
        if f in tiles:
            for d in daughters:
                if d in tiles:
                    married_out_links.append((f, d))

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
                        sib_groups, married_out_links)
