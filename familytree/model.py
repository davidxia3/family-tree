"""Data model + YAML loader for the 史记 family tree.

Genealogy is stored as DATA (data/shiji.yaml):
  - people:         one record per individual Shiji NAMES; id == the Chinese name
  - marriages:      husband_id / wife_id edges (childless unions, married-in daughters)
  - descended_from: soft "descended-from" edges (person mentioned only as a descendant)

Parent->child links live ON the child (father_id / mother_id / birth_order),
because every person has at most one father and one mother — this structurally
prevents duplicate/contradictory parent edges.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import yaml

PERSON_FIELDS = {
    "id", "name", "father_id", "mother_id", "birth_order",
    "color", "house", "chapter", "note",
}


@dataclass
class Person:
    id: str
    name: str
    father_id: Optional[str] = None
    mother_id: Optional[str] = None
    birth_order: Optional[int] = None   # 1 = eldest among the anchor parent's children
    color: Optional[str] = None         # "#rrggbb"; if unset, default fill is used
    house: Optional[str] = None         # metadata only (does NOT auto-color)
    chapter: Optional[str] = None       # Shiji source chapter; metadata only
    note: Optional[str] = None


@dataclass
class Marriage:
    husband_id: Optional[str] = None
    wife_id: Optional[str] = None


@dataclass
class DescendedFrom:
    person_id: Optional[str] = None
    ancestor_id: Optional[str] = None
    mentioned_with: Optional[str] = None   # render on this person's generation row
    depth: Optional[int] = None            # OR render this many generations below the ancestor
    order: Optional[int] = None            # rank among an ancestor's phantom descendants (1 = senior/right)


@dataclass
class Dataset:
    people: List[Person] = field(default_factory=list)
    marriages: List[Marriage] = field(default_factory=list)
    descended_from: List[DescendedFrom] = field(default_factory=list)
    # Parentless sibling groups: each a list of member ids, ELDEST FIRST. Use when Shiji names
    # people as siblings but their shared parent is not a tile in the tree (rule Sib).
    siblings: List[List[str]] = field(default_factory=list)


@dataclass
class Index:
    """Derived relationship maps, built once from a Dataset."""
    id_to_person: Dict[str, Person]
    children_of: Dict[str, List[Person]]   # father_id -> children, sorted by birth_order
    wives_of: Dict[str, List[str]]         # host id -> LEFT-side wife tiles, in slot order
    husbands_of: Dict[str, List[str]]      # host id -> RIGHT-side husband tiles (free-root in-laws)
    husband_of: Dict[str, str]             # spouse-tile id -> the host node it attaches to
    wife_persons: Set[str]                 # all ids rendered as spouse-tiles (not standalone nodes)
    descended: List[DescendedFrom]
    inlaw_sib_of: Dict[str, List[str]]     # host id -> parentless in-law sibs attached on its right (rtl)
    sib_host: Dict[str, str]               # in-law sib id -> the host node it attaches to
    inlaw_sib_persons: Set[str]            # in-law sibs rendered as attached tiles (not standalone nodes)
    sibling_groups: List[List[str]]        # parentless sib-groups (member ids) for the sibling busbar


def _s(v) -> Optional[str]:
    return None if v is None else str(v)


def _coerce_person(d, problems: List[str]) -> Optional[Person]:
    if not isinstance(d, dict):
        problems.append(f"people: entry is not a mapping: {d!r}")
        return None
    pid = d.get("id")
    if pid is None:
        problems.append(f"people: entry missing id: {d!r}")
        return None
    pid = str(pid)
    name = d.get("name")
    name = pid if name is None else str(name)

    bo = d.get("birth_order")
    if bo is not None:
        try:
            bo = int(bo)
        except (TypeError, ValueError):
            problems.append(f"{pid}: birth_order is not an integer: {bo!r}")
            bo = None

    unknown = set(d) - PERSON_FIELDS
    if unknown:
        problems.append(f"{pid}: unknown field(s) {sorted(unknown)}")

    return Person(
        id=pid, name=name,
        father_id=_s(d.get("father_id")), mother_id=_s(d.get("mother_id")),
        birth_order=bo, color=_s(d.get("color")), house=_s(d.get("house")),
        chapter=_s(d.get("chapter")), note=_s(d.get("note")),
    )


def load_dataset(path: str) -> Tuple[Dataset, List[str]]:
    """Load YAML into a Dataset. Returns (dataset, load_problems).

    Tolerant by design: malformed entries are skipped and reported rather than
    raising, so a partial tree never crashes the pipeline.
    """
    problems: List[str] = []
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        return Dataset(), ["top-level YAML is not a mapping (expected people:/marriages:/...)"]

    people: List[Person] = []
    for d in (raw.get("people") or []):
        p = _coerce_person(d, problems)
        if p is not None:
            people.append(p)

    marriages: List[Marriage] = []
    for d in (raw.get("marriages") or []):
        if isinstance(d, dict):
            marriages.append(Marriage(husband_id=_s(d.get("husband_id")), wife_id=_s(d.get("wife_id"))))
        else:
            problems.append(f"marriages: entry is not a mapping: {d!r}")

    desc: List[DescendedFrom] = []
    for d in (raw.get("descended_from") or []):
        if isinstance(d, dict):
            dep = d.get("depth")
            if dep is not None:
                try:
                    dep = int(dep)
                except (TypeError, ValueError):
                    problems.append(f"descended_from: depth is not an integer: {dep!r}")
                    dep = None
            ordr = d.get("order")
            if ordr is not None:
                try:
                    ordr = int(ordr)
                except (TypeError, ValueError):
                    problems.append(f"descended_from: order is not an integer: {ordr!r}")
                    ordr = None
            desc.append(DescendedFrom(person_id=_s(d.get("person_id")), ancestor_id=_s(d.get("ancestor_id")),
                                      mentioned_with=_s(d.get("mentioned_with")), depth=dep, order=ordr))
        else:
            problems.append(f"descended_from: entry is not a mapping: {d!r}")

    sibs: List[List[str]] = []
    for grp in (raw.get("siblings") or []):
        if isinstance(grp, list) and len(grp) >= 2:
            sibs.append([str(m) for m in grp])
        else:
            problems.append(f"siblings: entry is not a list of >=2 ids: {grp!r}")

    return Dataset(people, marriages, desc, sibs), problems


def build_index(ds: Dataset) -> Index:
    id_to = {p.id: p for p in ds.people}

    children_of: Dict[str, List[Person]] = {}
    for p in ds.people:
        if p.father_id and p.father_id in id_to:
            children_of.setdefault(p.father_id, []).append(p)
    for kids in children_of.values():
        kids.sort(key=lambda c: (c.birth_order if c.birth_order is not None else 10 ** 9, c.name, c.id))

    # Who is a parent of someone in the chart? (used to spot "free roots".)
    parents: Set[str] = set()
    for p in ds.people:
        if p.father_id in id_to:
            parents.add(p.father_id)
        if p.mother_id in id_to:
            parents.add(p.mother_id)

    def free_root(pid: str) -> bool:        # no ancestry and no children of their own
        p = id_to[pid]
        return p.father_id not in id_to and p.mother_id not in id_to and pid not in parents

    def rooted(pid: str) -> bool:           # has a place in the tree via a parent
        p = id_to[pid]
        return p.father_id in id_to or p.mother_id in id_to

    # FLIP (married-out daughter): a free-root husband married to a rooted wife becomes a
    # RIGHT-side tile beside her — she stays a node under her father, wife-left/husband-right.
    flip_husbands: Dict[str, str] = {}      # husband id -> wife (host)
    for m in ds.marriages:
        if m.husband_id in id_to and m.wife_id in id_to:
            if free_root(m.husband_id) and rooted(m.wife_id):
                flip_husbands[m.husband_id] = m.wife_id

    # LEFT-side wife tiles: named mothers (present father) + non-flip marriage wives.
    wife_persons: Set[str] = set()
    for p in ds.people:
        if (p.mother_id and p.mother_id in id_to and p.father_id and p.father_id in id_to):
            wife_persons.add(p.mother_id)
    for m in ds.marriages:
        if m.wife_id in id_to and m.husband_id in id_to and m.husband_id not in flip_husbands:
            wife_persons.add(m.wife_id)

    # Wife slot order: David sets it MANUALLY via the order wives appear in `marriages`
    # (slot 1 = beside the husband). A wife known only as a mother (no marriage entry) is
    # appended after, by her most-senior child then id. (No auto child-seniority ordering.)
    marriage_pos: Dict[Tuple[str, str], int] = {}
    for i, m in enumerate(ds.marriages):
        marriage_pos.setdefault((m.husband_id, m.wife_id), i)
    child_rank: Dict[Tuple[str, str], int] = {}
    hus_wives: Dict[str, Set[str]] = {}
    for p in ds.people:
        if (p.mother_id and p.mother_id in id_to and p.father_id and p.father_id in id_to):
            key = (p.father_id, p.mother_id)
            r = p.birth_order if p.birth_order is not None else 10 ** 9
            child_rank[key] = min(child_rank.get(key, 10 ** 18), r)
            hus_wives.setdefault(p.father_id, set()).add(p.mother_id)
    for m in ds.marriages:
        if m.wife_id in id_to and m.husband_id in id_to and m.husband_id not in flip_husbands:
            hus_wives.setdefault(m.husband_id, set()).add(m.wife_id)

    wives_of: Dict[str, List[str]] = {}
    husband_of: Dict[str, str] = {}
    for h, wives in hus_wives.items():
        ordered = sorted(wives, key=lambda w: (
            marriage_pos.get((h, w), 10 ** 9),          # manual order via `marriages` list
            child_rank.get((h, w), 10 ** 18), w))        # fallback: mother-only wives
        wives_of[h] = ordered
        for w in ordered:
            husband_of.setdefault(w, h)

    # RIGHT-side husband tiles (the flips).
    husbands_of: Dict[str, List[str]] = {}
    for hbnd, wife in sorted(flip_husbands.items()):
        husbands_of.setdefault(wife, []).append(hbnd)
        husband_of.setdefault(hbnd, wife)
        wife_persons.add(hbnd)

    # Parentless sibling groups (rule Sib): if one member married INTO the tree (a spouse tile),
    # the others attach to that member's partner on the partner's senior (right, rtl) side, in
    # eldest-first order; the whole group is tied by a stub-less sibling busbar (drawn in render).
    inlaw_sib_of: Dict[str, List[str]] = {}
    sib_host: Dict[str, str] = {}
    inlaw_sib_persons: Set[str] = set()
    sibling_groups: List[List[str]] = []
    for grp in ds.siblings:
        members = [m for m in grp if m in id_to]
        if len(members) < 2:
            continue
        sibling_groups.append(members)
        anchor = next((m for m in members if m in husband_of), None)   # the married-in member
        if anchor is None:
            continue
        host = husband_of[anchor]
        for m in members:
            if m != anchor:
                inlaw_sib_persons.add(m)
                sib_host[m] = host
                inlaw_sib_of.setdefault(host, []).append(m)

    return Index(id_to, children_of, wives_of, husbands_of, husband_of, wife_persons,
                 list(ds.descended_from), inlaw_sib_of, sib_host, inlaw_sib_persons, sibling_groups)
