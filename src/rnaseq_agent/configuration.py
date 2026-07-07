from __future__ import annotations

from copy import deepcopy
from typing import Any

from .defaults import DEFAULT_PIPELINE, DEFAULT_REFERENCE


def normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(config)

    reference = {**DEFAULT_REFERENCE, **normalized.get("reference", {})}
    normalized["reference"] = reference

    server = normalized.setdefault("server", {})
    server.setdefault("shell", "bash")
    server.setdefault("init_commands", [])

    normalized.setdefault(
        "polling",
        {
            "interval_seconds": 300,
            "timeout_hours": 168,
        },
    )

    pipeline = normalized.setdefault("pipeline", {})
    for step, defaults in DEFAULT_PIPELINE.items():
        pipeline.setdefault(step, defaults.copy())
        pipeline[step].setdefault("enabled", defaults["enabled"])
        pipeline[step].setdefault("version", defaults["version"])

    normalized.setdefault("notification", {"email_enabled": False})
    normalized.setdefault("sequencing", {"layout": "paired", "strandedness": "auto"})
    normalized.setdefault("samples", {"items": []})
    return normalized
