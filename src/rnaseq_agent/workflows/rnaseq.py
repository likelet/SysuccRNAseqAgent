from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..defaults import DEFAULT_PIPELINE, DEFAULT_REFERENCE
from ..pipeline import render_env_setup_script, render_remote_pipeline_script, render_submit_script


class RNASeqWorkflow:
    name = "rnaseq"
    label = "Bulk RNA-seq"
    result_dirs = ("logs", "fastp", "star", "arriba", "featurecounts", "rsem", "status")

    def default_reference(self) -> dict[str, Any]:
        return deepcopy(DEFAULT_REFERENCE)

    def default_pipeline(self) -> dict[str, Any]:
        return deepcopy(DEFAULT_PIPELINE)

    def normalize_config(self, config: dict[str, Any]) -> dict[str, Any]:
        config["reference"] = {**self.default_reference(), **config.get("reference", {})}

        pipeline = config.setdefault("pipeline", {})
        for step, defaults in self.default_pipeline().items():
            pipeline.setdefault(step, defaults.copy())
            pipeline[step].setdefault("enabled", defaults["enabled"])
            pipeline[step].setdefault("version", defaults["version"])

        return config

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        pipeline = config.get("pipeline", {})
        errors: list[str] = []
        star_enabled = pipeline.get("star", {}).get("enabled", True)

        dependent_steps = ("arriba", "featurecounts", "rsem")
        for step in dependent_steps:
            if pipeline.get(step, {}).get("enabled", False) and not star_enabled:
                errors.append(f"{step} requires star to be enabled.")

        reference = config.get("reference", {})
        required_reference_keys = []
        if pipeline.get("star", {}).get("enabled", True):
            required_reference_keys.append("star_index_dir")
        if pipeline.get("featurecounts", {}).get("enabled", False) or pipeline.get("arriba", {}).get("enabled", False):
            required_reference_keys.append("remote_gtf_path")
        if pipeline.get("arriba", {}).get("enabled", False):
            required_reference_keys.append("remote_genome_fasta_path")
        if pipeline.get("rsem", {}).get("enabled", False):
            required_reference_keys.append("rsem_index_prefix")

        for key in required_reference_keys:
            if not reference.get(key):
                errors.append(f"Missing required reference setting: {key}")

        return errors

    def render_env_setup_script(self, config: dict[str, Any]) -> str:
        return render_env_setup_script(config)

    def render_pipeline_script(self, config: dict[str, Any]) -> str:
        return render_remote_pipeline_script(config)

    def render_submit_script(self, config: dict[str, Any]) -> str:
        return render_submit_script(config)
