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
    mentioned_with: Optional[str] = None   # whose generation row the descendant is drawn on


@dataclass
class Dataset:
    people: List[Person] = field(default_factory=list)
    marriages: List[Marriage] = field(default_factory=list)
    descended_from: List[DescendedFrom] = field(default_factory=list)


@dataclass
class Index:
    """Derived relationship maps, built once from a Dataset."""
    id_to_person: Dict[str, Person]
    children_of: Dict[str, List[Person]]   # father_id -> children, sorted by birth_order
    wives_of: Dict[str, List[str]]         # husband/father id -> wife ids in slot order
    husband_of: Dict[str, str]             # wife id -> the husband/father she attaches to
    wife_persons: Set[str]                 # ids rendered as wife-tiles (not standalone nodes)
    descended: List[DescendedFrom]


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
            desc.append(DescendedFrom(person_id=_s(d.get("person_id")), ancestor_id=_s(d.get("ancestor_id")),
                                      mentioned_with=_s(d.get("mentioned_with"))))
        else:
            problems.append(f"descended_from: entry is not a mapping: {d!r}")

    return Dataset(people, marriages, desc), problems


def build_index(ds: Dataset) -> Index:
    id_to = {p.id: p for p in ds.people}

    children_of: Dict[str, List[Person]] = {}
    for p in ds.people:
        if p.father_id and p.father_id in id_to:
            children_of.setdefault(p.father_id, []).append(p)
    for kids in children_of.values():
        kids.sort(key=lambda c: (c.birth_order if c.birth_order is not None else 10 ** 9, c.name, c.id))

    # A person is rendered as a WIFE-TILE (attached to a husband/father) when she
    # is a named mother of someone whose father is also present, or an explicit
    # marriage wife with the husband present.
    wife_persons: Set[str] = set()
    for p in ds.people:
        if (p.mother_id and p.mother_id in id_to and p.father_id and p.father_id in id_to):
            wife_persons.add(p.mother_id)
    for m in ds.marriages:
        if m.wife_id in id_to and m.husband_id in id_to:
            wife_persons.add(m.wife_id)

    # Wife slot order (rule 6): a wife's rank is the seniority of her most-senior
    # child by that husband; childless wives sort after, by id.
    rank: Dict[Tuple[str, str], int] = {}
    hus_wives: Dict[str, Set[str]] = {}
    for p in ds.people:
        if (p.mother_id and p.mother_id in id_to and p.father_id and p.father_id in id_to):
            key = (p.father_id, p.mother_id)
            r = p.birth_order if p.birth_order is not None else 10 ** 9
            rank[key] = min(rank.get(key, 10 ** 18), r)
            hus_wives.setdefault(p.father_id, set()).add(p.mother_id)
    for m in ds.marriages:
        if m.wife_id in id_to and m.husband_id in id_to:
            hus_wives.setdefault(m.husband_id, set()).add(m.wife_id)

    wives_of: Dict[str, List[str]] = {}
    husband_of: Dict[str, str] = {}
    for h, wives in hus_wives.items():
        ordered = sorted(wives, key=lambda w: (rank.get((h, w), 10 ** 18), w))
        wives_of[h] = ordered
        for w in ordered:
            husband_of.setdefault(w, h)

    return Index(id_to, children_of, wives_of, husband_of, wife_persons, list(ds.descended_from))
