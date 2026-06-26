"""史记 family tree — semi-manual SVG genealogy.

There is no genealogy database. positions.yaml is the single, self-contained data
file: one entity per tile (carrying its own name + color) plus the connector lines
you draw. Tiles are placed by hand in a standalone HTML editor; a renderer emits
the SVG.

Modules:
  config   — load config.yaml (sizes + colour pairs); derive the rest
  editor   — generate the standalone HTML grid-positioning editor
  render   — positions.yaml -> SVG (all styling in <defs>/CSS)
  cli      — edit | render
"""

__version__ = "0.3.0"
