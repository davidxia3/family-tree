"""史记 family tree — data-driven SVG genealogy.

Modules are intentionally separate:
  model    — dataclasses + YAML loader + relationship index
  validate — integrity checks (never crashes on partial data)
  layout   — tidy-tree + genealogy rules -> (x, y) per tile
  render   — positions -> SVG (all styling in <defs>/CSS)
  cli      — build | validate | status
"""

__version__ = "0.1.0"
