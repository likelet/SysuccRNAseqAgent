from __future__ import annotations

from typing import Any

from ..pipeline import render_env_setup_script, render_remote_pipeline_script, render_submit_script


class RNASeqWorkflow:
    name = "rnaseq"
    label = "Bulk RNA-seq"
    result_dirs = ("logs", "fastp", "star", "arriba", "featurecounts", "rsem", "status")

    def render_env_setup_script(self, config: dict[str, Any]) -> str:
        return render_env_setup_script(config)

    def render_pipeline_script(self, config: dict[str, Any]) -> str:
        return render_remote_pipeline_script(config)

    def render_submit_script(self, config: dict[str, Any]) -> str:
        return render_submit_script(config)
