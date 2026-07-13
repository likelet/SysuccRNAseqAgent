from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .workflows import get_workflow


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    checked_files: int
    missing_files: list[Path]
    errors: list[str]


def validate_local_fastqs(config: dict[str, Any]) -> ValidationResult:
    samples = config["samples"]
    local_data_dir = Path(samples["local_data_dir"])
    paired = config.get("sequencing", {}).get("layout", "paired") == "paired"
    missing: list[Path] = []
    checked = 0
    errors = _sample_errors(config)

    for sample in samples.get("items", []):
        keys = ("fastq_1", "fastq_2") if paired else ("fastq_1",)
        for key in keys:
            fastq = sample.get(key)
            if not fastq:
                continue
            checked += 1
            path = local_data_dir / fastq
            if not path.exists():
                missing.append(path)

    errors.extend(get_workflow(config).validate_config(config))
    return ValidationResult(ok=not missing and not errors, checked_files=checked, missing_files=missing, errors=errors)


def _sample_errors(config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    samples = config.get("samples", {})
    items = samples.get("items", [])
    paired = config.get("sequencing", {}).get("layout", "paired") == "paired"

    if not items:
        errors.append("At least one sample is required.")

    if not samples.get("local_data_dir"):
        errors.append("Missing samples.local_data_dir.")
    if not samples.get("remote_data_dir"):
        errors.append("Missing samples.remote_data_dir.")

    seen_ids: set[str] = set()
    for index, sample in enumerate(items, start=1):
        sample_id = sample.get("sample_id")
        if not sample_id:
            errors.append(f"Sample {index} is missing sample_id.")
        elif sample_id in seen_ids:
            errors.append(f"Duplicate sample_id: {sample_id}")
        else:
            seen_ids.add(sample_id)

        if not sample.get("fastq_1"):
            errors.append(f"Sample {sample_id or index} is missing fastq_1.")
        if paired and not sample.get("fastq_2"):
            errors.append(f"Sample {sample_id or index} is missing fastq_2 for paired-end sequencing.")

    server = config.get("server", {})
    if not server.get("remote_workdir"):
        errors.append("Missing server.remote_workdir.")

    return errors
