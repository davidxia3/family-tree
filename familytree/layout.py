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

from dataclasses import dataclass
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

    node_ids = [p.id for p in ds.people if p.id not in wife_persons]
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

    # Note 3: a descendant-only person is treated as a phantom YOUNGEST child of
    # the ancestor (so the ancestor centers over it and a SOLID line is drawn to
    # it), even though it is RENDERED lower, on another generation's row.
    descendant_render_ref: Dict[str, Optional[str]] = {}
    for d in idx.descended:
        P, anc = d.person_id, d.ancestor_id
        if P in node_set and anc in node_set:
            if P in roots:
                roots.remove(P)
            anchor_children.setdefault(anc, []).append(P)
            descendant_render_ref[P] = d.mentioned_with

    def child_sort_key(cid: str):
        c = id_to[cid]
        return (c.birth_order if c.birth_order is not None else 10 ** 9, c.name, c.id)

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
                stack.append((c, g + 1, seen2))

    for r in roots:
        assign_gen(r)

    secondary: List[Tuple[str, str, str]] = []

    # wife tiles share the husband's row (rules 6-7)
    for w in wife_persons:
        h = idx.husband_of.get(w)
        if h is not None and h in gen:
            gen[w] = gen[h]

    # Note 3: a descendant-only person is RENDERED on the row of the person it was
    # mentioned with (its x already comes from being a phantom child of the ancestor).
    render_gen = dict(gen)
    for P, ref in descendant_render_ref.items():
        if ref and ref in gen:
            render_gen[P] = gen[ref]

    # married-in daughter keeps a dashed link to her father (primary-placement / DAG rule)
    for p in ds.people:
        if p.id in wife_persons and p.father_id and p.father_id in id_to:
            secondary.append((p.father_id, p.id, "father"))

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
            visiting.discard(nid)
            return Block(X, {g: -half}, {g: max(half, wright)})

        blocks = [layout_block(c) for c in kids]
        for c, b in zip(kids, blocks):
            _shift_block(b, -b.x[c])             # normalize child head to 0
        offsets, mL, mR = _pack(blocks, h_gap)
        node_x = (offsets[0] + offsets[-1]) / 2.0  # center over first..last child (rule 4)

        X = {nid: 0.0}
        for c, b, o in zip(kids, blocks, offsets):
            for pid, px in b.x.items():
                X[pid] = px + o - node_x
        Lc = {gg: v - node_x for gg, v in mL.items()}
        Rc = {gg: v - node_x for gg, v in mR.items()}

        wright = place_wives(nid, X, 0.0)
        Lc[g] = min(Lc.get(g, -half), -half)
        Rc[g] = max(Rc.get(g, half), max(half, wright))
        visiting.discard(nid)
        return Block(X, Lc, Rc)

    root_blocks: List[Block] = []
    for r in roots:
        b = layout_block(r)
        _shift_block(b, -b.x[r])
        root_blocks.append(b)

    final_x: Dict[str, float] = {}
    if root_blocks:
        offsets, _, _ = _pack(root_blocks, h_gap)
        for r, b, o in zip(roots, root_blocks, offsets):
            for pid, px in b.x.items():
                final_x[pid] = px + o

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

    families = [(f, kids[:]) for f, kids in anchor_children.items() if f in tiles]

    marriages: List[Tuple[str, str]] = []
    for h, wives in idx.wives_of.items():
        prev = h
        for w in wives:
            if prev in tiles and w in tiles:
                marriages.append((prev, w))
            prev = w

    secondary = [(a, b, k) for (a, b, k) in secondary if a in tiles and b in tiles]
    unplaced = [p.id for p in ds.people if p.id not in tiles]

    return LayoutResult(tiles, families, marriages, secondary, width, height, roots, unplaced)
