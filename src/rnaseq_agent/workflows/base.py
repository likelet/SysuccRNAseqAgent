from __future__ import annotations

from typing import Any, Protocol


class Workflow(Protocol):
    name: str
    label: str
    result_dirs: tuple[str, ...]

    def render_env_setup_script(self, config: dict[str, Any]) -> str:
        ...

    def render_pipeline_script(self, config: dict[str, Any]) -> str:
        ...

    def render_submit_script(self, config: dict[str, Any]) -> str:
        ...
