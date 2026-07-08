"""Human-readable `--format table` rendering, an alternative to the JSON envelope."""

from __future__ import annotations

from typing import Any


def _format_cell(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def render_table(rows: list[dict[str, Any]]) -> str:
    """Render a list of flat dicts as an aligned, human-readable table."""
    if not rows:
        return "(no rows)"

    columns = list(rows[0].keys())
    formatted = [{c: _format_cell(row.get(c)) for c in columns} for row in rows]
    widths = {c: max(len(c), *(len(r[c]) for r in formatted)) for c in columns}

    def render_row(values: dict[str, str]) -> str:
        return "  ".join(values[c].ljust(widths[c]) for c in columns)

    header = render_row({c: c for c in columns})
    separator = "  ".join("-" * widths[c] for c in columns)
    body = [render_row(r) for r in formatted]
    return "\n".join([header, separator, *body])
