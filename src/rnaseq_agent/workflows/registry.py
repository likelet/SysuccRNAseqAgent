from __future__ import annotations

from typing import Any

from .base import Workflow
from .rnaseq import RNASeqWorkflow


_WORKFLOWS: dict[str, Workflow] = {
    RNASeqWorkflow.name: RNASeqWorkflow(),
}


def list_workflows() -> list[Workflow]:
    return list(_WORKFLOWS.values())


def get_workflow(config: dict[str, Any]) -> Workflow:
    workflow_name = config.get("workflow", {}).get("type", "rnaseq")
    try:
        return _WORKFLOWS[workflow_name]
    except KeyError as exc:
        available = ", ".join(sorted(_WORKFLOWS))
        raise ValueError(f"Unsupported workflow type: {workflow_name}. Available workflows: {available}") from exc
