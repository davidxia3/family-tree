"""Comment-preserving text edits for the data YAML.

PyYAML round-trips would drop the inline comments you annotate as you read, so
add/set operations are targeted text edits (append a list item, or set fields
inside a person block). Every edit is re-parsed to confirm the file is still
valid YAML before it is written.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

import yaml

# A scalar is safe to write unquoted if it does not start with a YAML indicator
# and contains no ':' or '#' (which would start a mapping or a comment).
_SAFE = re.compile(r"^[^\s#&*!|>%@`?{}\[\],:'\"-][^:#]*$")
_BOOLISH = {"true", "false", "yes", "no", "null", "~", "on", "off"}


def scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    s = str(v)
    if s == "" or not _SAFE.match(s) or s.lower() in _BOOLISH:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def read_lines(path: str) -> List[str]:
    with open(path, encoding="utf-8") as f:
        return f.read().splitlines()


def write_lines(path: str, lines: List[str]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def parse_ok(lines: List[str]) -> Tuple[bool, Optional[str]]:
    try:
        yaml.safe_load("\n".join(lines) + "\n")
        return True, None
    except yaml.YAMLError as e:
        return False, str(e)


def _header_index(lines: List[str], key: str) -> int:
    pat = re.compile(rf"^{re.escape(key)}\s*:")
    for i, ln in enumerate(lines):
        if pat.match(ln):
            return i
    return -1


def _next_toplevel(lines: List[str], start: int) -> int:
    for i in range(start, len(lines)):
        ln = lines[i]
        if ln and not ln[0].isspace() and not ln.lstrip().startswith("#") and ":" in ln:
            return i
    return len(lines)


def append_item(lines: List[str], key: str, item_lines: List[str]) -> List[str]:
    """Append a list item under top-level `key`, after the section's last item."""
    hdr = _header_index(lines, key)
    if hdr == -1:                                   # no such section yet: create it
        if lines and lines[-1].strip() != "":
            lines.append("")
        lines.append(f"{key}:")
        lines.extend(item_lines)
        return lines
    if re.match(rf"^{re.escape(key)}\s*:\s*\[\s*\]\s*$", lines[hdr]):   # "key: []" -> block
        lines[hdr] = f"{key}:"
        lines[hdr + 1:hdr + 1] = item_lines
        return lines
    end = _next_toplevel(lines, hdr + 1)
    ins = end
    while ins - 1 > hdr and lines[ins - 1].strip() == "":   # back up over trailing blanks
        ins -= 1
    lines[ins:ins] = item_lines
    return lines


def person_block(lines: List[str], pid: str) -> Optional[Tuple[int, int, int]]:
    """Return (start, end, indent) line span of a person record, or None."""
    # Capture the id token only — a quoted string or a run of non-space — so an
    # inline comment after the value (e.g. `- id: 黃帝   # 少典之子`) is ignored.
    pat = re.compile(r'^(\s*)-\s+id\s*:\s*("(?:[^"\\]|\\.)*"|\S+)')
    for i, ln in enumerate(lines):
        m = pat.match(ln)
        if m and _unquote(m.group(2)) == pid:
            indent = len(m.group(1))
            j = i + 1
            while j < len(lines):
                ln2 = lines[j]
                if ln2.strip() == "":
                    j += 1
                    continue
                if (len(ln2) - len(ln2.lstrip())) <= indent:   # next item / top-level key
                    break
                j += 1
            return i, j, indent
    return None


def set_person_fields(lines: List[str], pid: str, fields: Dict[str, object]) -> bool:
    blk = person_block(lines, pid)
    if not blk:
        return False
    start, end, indent = blk
    fi = " " * (indent + 2)
    insert_after = start
    for k in range(start, end):
        if re.match(rf"^{fi}name\s*:", lines[k]):
            insert_after = k
            break
    for field, val in fields.items():
        if val is None:
            continue
        new_line = f"{fi}{field}: {scalar(val)}"
        replaced = False
        for k in range(start, end):
            if re.match(rf"^{fi}{re.escape(field)}\s*:", lines[k]):
                lines[k] = new_line
                replaced = True
                break
        if not replaced:
            lines.insert(insert_after + 1, new_line)
            insert_after += 1
            end += 1
    return True


def person_item_lines(pid, name=None, father=None, mother=None, order=None,
                      color=None, house=None, chapter=None, note=None) -> List[str]:
    out = [f"  - id: {scalar(pid)}",
           f"    name: {scalar(name if name is not None else pid)}"]
    for field, val in (("father_id", father), ("mother_id", mother), ("birth_order", order),
                       ("color", color), ("house", house), ("chapter", chapter), ("note", note)):
        if val is not None:
            out.append(f"    {field}: {scalar(val)}")
    return out
