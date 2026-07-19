"""Convert DB rows / nested values into JSON-safe plain types."""

from __future__ import annotations

from typing import Any


def plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    # sqlite Row
    if hasattr(value, "keys") and hasattr(value, "__getitem__"):
        try:
            return {k: plain(value[k]) for k in value.keys()}
        except Exception:
            pass
    return str(value)


def character_dict(row) -> dict:
    return plain({k: row[k] for k in row.keys()})
