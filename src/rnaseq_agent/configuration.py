from __future__ import annotations

from copy import deepcopy
from typing import Any

from .workflows import get_workflow


def normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized = deepcopy(config)
    normalized.setdefault("workflow", {"type": "rnaseq", "label": "Bulk RNA-seq"})

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

    normalized.setdefault("notification", {"email_enabled": False})
    normalized.setdefault("sequencing", {"layout": "paired", "strandedness": "auto"})
    normalized.setdefault("samples", {"items": []})

    workflow = get_workflow(normalized)
    normalized["workflow"].setdefault("label", workflow.label)
    return workflow.normalize_config(normalized)
