from __future__ import annotations

from typing import Any, Protocol


class Workflow(Protocol):
    name: str
    label: str
    result_dirs: tuple[str, ...]

    def default_reference(self) -> dict[str, Any]:
        ...

    def default_pipeline(self) -> dict[str, Any]:
        ...

    def normalize_config(self, config: dict[str, Any]) -> dict[str, Any]:
        ...

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        ...

    def render_env_setup_script(self, config: dict[str, Any]) -> str:
        ...

    def render_pipeline_script(self, config: dict[str, Any]) -> str:
        ...

    def render_submit_script(self, config: dict[str, Any]) -> str:
        ...
