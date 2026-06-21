"""Integrity checks. Returns a list of (level, message); never raises on bad data.

ERROR = will distort or break the tree if rendered as-is.
WARN  = probably a data-entry gap (e.g. missing birth_order).
INFO  = neutral observations.
"""
from __future__ import annotations

from typing import List, Tuple

from .model import Dataset

ERROR = "ERROR"
WARN = "WARN"
INFO = "INFO"

Issue = Tuple[str, str]


def validate(ds: Dataset) -> List[Issue]:
    issues: List[Issue] = []

    id_to = {}
    for p in ds.people:
        if p.id in id_to:
            issues.append((ERROR, f"duplicate id: {p.id!r}"))
        id_to[p.id] = p

    def exists(i) -> bool:
        return bool(i) and i in id_to

    # --- per-person reference + birth_order checks ---
    for p in ds.people:
        if p.father_id and not exists(p.father_id):
            issues.append((ERROR, f"{p.id}: father_id -> unknown id {p.father_id!r}"))
        if p.mother_id and not exists(p.mother_id):
            issues.append((ERROR, f"{p.id}: mother_id -> unknown id {p.mother_id!r} (must be a named record or null)"))
        if p.father_id == p.id or p.mother_id == p.id:
            issues.append((ERROR, f"{p.id}: listed as its own parent"))
        if (exists(p.father_id) or exists(p.mother_id)) and p.birth_order is None:
            issues.append((WARN, f"{p.id}: missing birth_order"))

    # --- duplicate birth_order among one father's children ---
    by_father = {}
    for p in ds.people:
        if exists(p.father_id):
            by_father.setdefault(p.father_id, []).append(p)
    for f, kids in by_father.items():
        seen = {}
        for c in kids:
            if c.birth_order is None:
                continue
            if c.birth_order in seen:
                issues.append((WARN, f"father {f}: birth_order {c.birth_order} used by both {seen[c.birth_order]} and {c.id}"))
            else:
                seen[c.birth_order] = c.id

    # --- lineage cycle detection (over father/mother edges) ---
    color = {}  # 0/absent=unvisited, 1=on-stack, 2=done

    def dfs(start: str):
        stack = [(start, 0)]
        path = []  # ids currently on the recursion stack
        while stack:
            node, state = stack.pop()
            if state == 0:
                if color.get(node) == 2:
                    continue
                color[node] = 1
                path.append(node)
                stack.append((node, 1))
                p = id_to.get(node)
                for nxt in ((p.father_id, p.mother_id) if p else ()):
                    if exists(nxt):
                        if color.get(nxt) == 1:
                            issues.append((ERROR, f"lineage cycle: {node} -> {nxt}"))
                        elif color.get(nxt, 0) == 0:
                            stack.append((nxt, 0))
            else:
                color[node] = 2
                if path and path[-1] == node:
                    path.pop()

    for p in ds.people:
        if color.get(p.id, 0) == 0:
            dfs(p.id)

    # --- marriages ---
    for m in ds.marriages:
        if not m.husband_id or not m.wife_id:
            issues.append((WARN, f"marriage with a missing side: husband={m.husband_id!r} wife={m.wife_id!r}"))
            continue
        if not exists(m.husband_id):
            issues.append((ERROR, f"marriage: unknown husband_id {m.husband_id!r}"))
        if not exists(m.wife_id):
            issues.append((ERROR, f"marriage: unknown wife_id {m.wife_id!r}"))
        if m.husband_id == m.wife_id:
            issues.append((ERROR, f"marriage: husband == wife ({m.husband_id})"))

    # --- descended_from ---
    for d in ds.descended_from:
        if not d.person_id or not d.ancestor_id:
            issues.append((WARN, f"descended_from with a missing side: {d.person_id!r} <- {d.ancestor_id!r}"))
            continue
        if not exists(d.person_id):
            issues.append((ERROR, f"descended_from: unknown person_id {d.person_id!r}"))
        if not exists(d.ancestor_id):
            issues.append((ERROR, f"descended_from: unknown ancestor_id {d.ancestor_id!r}"))
        if d.person_id == d.ancestor_id:
            issues.append((ERROR, f"descended_from: person == ancestor ({d.person_id})"))
        if d.mentioned_with and not exists(d.mentioned_with):
            issues.append((ERROR, f"descended_from: unknown mentioned_with {d.mentioned_with!r}"))
        if d.depth is not None and d.depth < 1:
            issues.append((ERROR, f"descended_from: {d.person_id} depth must be >= 1 (got {d.depth})"))
        if d.depth is not None and d.mentioned_with:
            issues.append((WARN, f"descended_from: {d.person_id} has both depth and mentioned_with; depth wins"))

    return issues
