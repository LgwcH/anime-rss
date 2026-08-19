"""Presentation-safe normalization for dicts and slotted core dataclasses."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any


def as_mapping(value: Any) -> dict[str, Any]:
    """Convert mappings, dataclasses and plain objects to a shallow dict."""

    if isinstance(value, Mapping):
        raw = dict(value)
    elif is_dataclass(value) and not isinstance(value, type):
        raw = asdict(value)
    else:
        exporter = getattr(value, "to_dict", None)
        if callable(exporter):
            exported = exporter()
            raw = dict(exported) if isinstance(exported, Mapping) else {}
        elif hasattr(value, "__dict__"):
            raw = dict(vars(value))
        else:
            raw = {}
    return {key: display_value(item) for key, item in raw.items()}


def display_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.astimezone().strftime("%Y-%m-%d %H:%M")
    if isinstance(value, list):
        return [display_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(display_value(item) for item in value)
    if isinstance(value, Mapping):
        return {key: display_value(item) for key, item in value.items()}
    return value


def progress_percent(value: Any) -> int:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0
    # Core tasks store progress in [0, 1], while UI-oriented controllers often
    # expose [0, 100].  Treat non-integral fractions as the former.
    if 0 <= number <= 1:
        number *= 100
    return max(0, min(100, round(number)))


def human_bytes(value: Any) -> str:
    if value in {None, ""}:
        return "—"
    if isinstance(value, str):
        return value
    try:
        size = float(value)
    except (TypeError, ValueError):
        return str(value)
    units = ("B", "KB", "MB", "GB", "TB")
    unit = units[0]
    for candidate in units:
        unit = candidate
        if abs(size) < 1024 or candidate == units[-1]:
            break
        size /= 1024
    return f"{size:.0f} {unit}" if unit in {"B", "KB"} else f"{size:.2f} {unit}"
