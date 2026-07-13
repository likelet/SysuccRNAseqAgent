from __future__ import annotations

import csv
import io
from copy import deepcopy
from typing import Any

from ..defaults import DEFAULT_PIPELINE, DEFAULT_REFERENCE
from ..pipeline import render_env_setup_script, render_remote_pipeline_script, render_submit_script
from ..shell import remote_path, shell_quote


class RNASeqWorkflow:
    name = "rnaseq"
    label = "Bulk RNA-seq"
    result_dirs = ("logs", "fastp", "star", "arriba", "featurecounts", "rsem", "status", "nfcore")

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

        execution = config.setdefault("execution", {})
        execution.setdefault("backend", "bash")
        nfcore = execution.setdefault("nfcore", {})
        nfcore.setdefault("pipeline", "nf-core/rnaseq")
        nfcore.setdefault("revision", "3.26.0")
        nfcore.setdefault("profile", "singularity")
        nfcore.setdefault("params", {})
        nfcore.setdefault("extra_args", "")
        return config

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        execution = config.get("execution", {})
        backend = execution.get("backend", "bash")
        if backend not in {"bash", "nfcore"}:
            return ["execution.backend must be 'bash' or 'nfcore'."]
        if backend == "nfcore":
            nfcore = execution.get("nfcore", {})
            errors = []
            if not nfcore.get("pipeline"):
                errors.append("Missing execution.nfcore.pipeline.")
            if not nfcore.get("profile"):
                errors.append("Missing execution.nfcore.profile.")
            return errors

        pipeline = config.get("pipeline", {})
        errors: list[str] = []
        star_enabled = pipeline.get("star", {}).get("enabled", True)
        reference = config.get("reference", {})

        if reference.get("auto_setup", True):
            for key in ("gtf_url", "genome_fasta_url", "remote_ref_dir", "remote_gtf_path", "remote_genome_fasta_path"):
                if not reference.get(key):
                    errors.append(f"Missing required reference setting for auto setup: {key}")

        dependent_steps = ("arriba", "featurecounts", "rsem")
        for step in dependent_steps:
            if pipeline.get(step, {}).get("enabled", False) and not star_enabled:
                errors.append(f"{step} requires star to be enabled.")

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
        if config.get("execution", {}).get("backend", "bash") == "nfcore":
            return self._render_nfcore_script(config)
        return render_remote_pipeline_script(config)

    def render_submit_script(self, config: dict[str, Any]) -> str:
        return render_submit_script(config)

    def _render_nfcore_script(self, config: dict[str, Any]) -> str:
        server = config["server"]
        reference = config["reference"]
        nfcore = config.get("execution", {}).get("nfcore", {})
        params = dict(nfcore.get("params") or {})
        if reference.get("nfcore_genome"):
            params.setdefault("genome", reference["nfcore_genome"])
        else:
            params.setdefault("fasta", reference["remote_genome_fasta_path"])
            params.setdefault("gtf", reference["remote_gtf_path"])

        revision = nfcore.get("revision")
        revision_arg = f" -r {shell_quote(revision)}" if revision else ""
        extra_args = nfcore.get("extra_args", "")
        command_lines = [
            f"nextflow run {shell_quote(nfcore['pipeline'])}{revision_arg} \\",
            f"  -profile {shell_quote(nfcore['profile'])} \\",
            "  --input nfcore/samplesheet.csv \\",
            "  --outdir nfcore/results \\",
        ]
        for key, value in sorted(params.items()):
            command_lines.append(f"  --{key} {shell_quote(str(value))} \\")
        if extra_args:
            command_lines.append(f"  {extra_args} \\")
        command_lines.append("  -resume")
        command = "\n".join(command_lines)

        env_setup_line = "source scripts/env_setup.sh" if server.get("init_commands") else ""
        prefix = f"{env_setup_line}\n\n" if env_setup_line else ""
        return f"""#!/usr/bin/env bash
set -euo pipefail

WORKDIR={shell_quote(config['server']['remote_workdir'])}
mkdir -p "$WORKDIR"/{{logs,scripts,status,nfcore}}
cd "$WORKDIR"

cleanup_failure() {{
  echo "failed" > status/state.txt
  date -Is > status/ended_at.txt
  touch status/failed.flag
}}
trap cleanup_failure ERR

echo "running" > status/state.txt
date -Is > status/started_at.txt

{prefix}cat > nfcore/samplesheet.csv <<'CSV'
{self._nfcore_samplesheet(config)}
CSV

{command}

echo "completed" > status/state.txt
date -Is > status/ended_at.txt
touch status/completed.flag
"""

    def _nfcore_samplesheet(self, config: dict[str, Any]) -> str:
        remote_data_dir = config["samples"]["remote_data_dir"]
        paired = config.get("sequencing", {}).get("layout", "paired") == "paired"
        strandedness = config.get("sequencing", {}).get("strandedness", "auto")
        seq_platform = config.get("sequencing", {}).get("seq_platform", "ILLUMINA")
        rows = []
        for sample in config["samples"]["items"]:
            rows.append(
                {
                    "sample": sample["sample_id"],
                    "fastq_1": remote_path(remote_data_dir, sample["fastq_1"]),
                    "fastq_2": remote_path(remote_data_dir, sample.get("fastq_2", "")) if paired else "",
                    "strandedness": strandedness,
                    "seq_platform": seq_platform,
                }
            )

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue().strip()
