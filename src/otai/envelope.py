"""Consistent JSON response envelope shared by every otai subcommand.

Success: {"ok": true, "data": {...}}
Failure: {"ok": false, "error": {"type": "...", "message": "..."}}
"""

from __future__ import annotations

from typing import Any


def success(data: dict[str, Any]) -> dict[str, Any]:
    """Build a success envelope wrapping the given data payload."""
    return {"ok": True, "data": data}


def failure(error_type: str, message: str) -> dict[str, Any]:
    """Build a failure envelope with a machine-readable type and human message."""
    return {"ok": False, "error": {"type": error_type, "message": message}}
