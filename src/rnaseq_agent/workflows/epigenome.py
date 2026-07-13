from __future__ import annotations

import csv
import io
from copy import deepcopy
from typing import Any

from ..pipeline import render_env_setup_script, render_submit_script
from ..shell import remote_path, shell_quote


EPIGENOME_REFERENCE = {
    "name": "GRCh38_epigenome_default",
    "species": "human",
    "assembly": "GRCh38",
    "genome_size": "hs",
    "bowtie2_index_prefix": "/data/ref/genomes/GRCh38/bowtie2/GRCh38",
    "bwa_index_prefix": "/data/ref/genomes/GRCh38/bwa/GRCh38.fa",
    "chromosome_sizes_path": "/data/ref/genomes/GRCh38/GRCh38.chrom.sizes",
    "blacklist_bed_path": "/data/ref/genomes/GRCh38/ENCFF356LFX.bed",
    "nfcore_genome": "GRCh38",
}


EPIGENOME_PIPELINE = {
    "fastp": {"enabled": True, "version": "0.24.1"},
    "alignment": {"enabled": True, "version": "bowtie2 2.5.x", "tool": "bowtie2"},
    "mark_duplicates": {"enabled": True, "version": "Picard 3.x", "tool": "picard"},
    "blacklist_filter": {"enabled": True, "version": "bedtools 2.31.x"},
    "bigwig": {"enabled": True, "version": "deepTools 3.5.x"},
    "peak_calling": {"enabled": True, "version": "MACS2 2.2.x", "tool": "macs2"},
}


class EpigenomeWorkflow:
    name = "epigenome"
    label = "Epigenome alignment and peak calling"
    nfcore_pipeline = ""
    nfcore_revision = ""
    nfcore_samplesheet_type = "atacseq"
    result_dirs = ("logs", "fastp", "align", "dedup", "filtered", "bigwig", "peaks", "qc", "status", "nfcore")
    macs_extra_args = ""
    default_peak_type = "narrow"

    def default_reference(self) -> dict[str, Any]:
        return deepcopy(EPIGENOME_REFERENCE)

    def default_pipeline(self) -> dict[str, Any]:
        return deepcopy(EPIGENOME_PIPELINE)

    def normalize_config(self, config: dict[str, Any]) -> dict[str, Any]:
        config["reference"] = {**self.default_reference(), **config.get("reference", {})}

        pipeline = config.setdefault("pipeline", {})
        for step, defaults in self.default_pipeline().items():
            pipeline.setdefault(step, defaults.copy())
            for key, value in defaults.items():
                pipeline[step].setdefault(key, value)
        pipeline["peak_calling"].setdefault("peak_type", self.default_peak_type)
        pipeline["peak_calling"].setdefault("extra_args", self.macs_extra_args)

        execution = config.setdefault("execution", {})
        execution.setdefault("backend", "bash")
        nfcore = execution.setdefault("nfcore", {})
        nfcore.setdefault("pipeline", self.nfcore_pipeline)
        nfcore.setdefault("revision", self.nfcore_revision)
        nfcore.setdefault("profile", "singularity")
        nfcore.setdefault("params", {})
        nfcore.setdefault("extra_args", "")
        return config

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        execution = config.get("execution", {})
        backend = execution.get("backend", "bash")
        if backend not in {"bash", "nfcore"}:
            errors.append("execution.backend must be 'bash' or 'nfcore'.")
            return errors

        if backend == "nfcore":
            nfcore = execution.get("nfcore", {})
            if not nfcore.get("pipeline"):
                errors.append("Missing execution.nfcore.pipeline.")
            if not nfcore.get("profile"):
                errors.append("Missing execution.nfcore.profile.")
            return errors

        pipeline = config.get("pipeline", {})
        reference = config.get("reference", {})
        alignment = pipeline.get("alignment", {})
        aligner = alignment.get("tool", "bowtie2")

        if alignment.get("enabled", True):
            if aligner == "bowtie2" and not reference.get("bowtie2_index_prefix"):
                errors.append("Missing required reference setting: bowtie2_index_prefix")
            elif aligner == "bwa" and not reference.get("bwa_index_prefix"):
                errors.append("Missing required reference setting: bwa_index_prefix")
            elif aligner not in {"bowtie2", "bwa"}:
                errors.append("pipeline.alignment.tool must be 'bowtie2' or 'bwa'.")

        if pipeline.get("peak_calling", {}).get("enabled", True) and not reference.get("genome_size"):
            errors.append("Missing required reference setting: genome_size")
        if pipeline.get("bigwig", {}).get("enabled", True) and not reference.get("chromosome_sizes_path"):
            errors.append("Missing required reference setting: chromosome_sizes_path")
        if pipeline.get("blacklist_filter", {}).get("enabled", True) and not reference.get("blacklist_bed_path"):
            errors.append("Missing required reference setting: blacklist_bed_path")

        return errors

    def render_env_setup_script(self, config: dict[str, Any]) -> str:
        return render_env_setup_script(config)

    def render_pipeline_script(self, config: dict[str, Any]) -> str:
        backend = config.get("execution", {}).get("backend", "bash")
        if backend == "nfcore":
            return self._render_nfcore_script(config)
        return self._render_bash_script(config)

    def render_submit_script(self, config: dict[str, Any]) -> str:
        return render_submit_script(config)

    def _render_bash_script(self, config: dict[str, Any]) -> str:
        server = config["server"]
        reference = config["reference"]
        sequencing = config["sequencing"]
        samples = config["samples"]["items"]
        pipeline = config["pipeline"]
        remote_data_dir = config["samples"]["remote_data_dir"]
        threads = int(server["threads"])
        paired = sequencing["layout"] == "paired"

        sample_blocks = []
        for sample in samples:
            sample_id = sample["sample_id"]
            raw_r1_path = remote_path(remote_data_dir, sample["fastq_1"])
            raw_r2_path = remote_path(remote_data_dir, sample.get("fastq_2", "")) if paired else ""
            raw_r1 = shell_quote(raw_r1_path)
            raw_r2 = shell_quote(raw_r2_path) if raw_r2_path else ""

            read1_expr = raw_r1
            read2_expr = raw_r2
            fastp_block = ""
            if pipeline["fastp"]["enabled"]:
                trim_r1 = shell_quote(f"fastp/{sample_id}.R1.fastq.gz")
                if paired:
                    trim_r2 = shell_quote(f"fastp/{sample_id}.R2.fastq.gz")
                    fastp_block = f"""
mkdir -p fastp
fastp \\
  -i {raw_r1} \\
  -I {raw_r2} \\
  -o {trim_r1} \\
  -O {trim_r2} \\
  --thread {threads} \\
  --json {shell_quote(f"fastp/{sample_id}.json")} \\
  --html {shell_quote(f"fastp/{sample_id}.html")}
""".strip()
                    read2_expr = trim_r2
                else:
                    fastp_block = f"""
mkdir -p fastp
fastp \\
  -i {raw_r1} \\
  -o {trim_r1} \\
  --thread {threads} \\
  --json {shell_quote(f"fastp/{sample_id}.json")} \\
  --html {shell_quote(f"fastp/{sample_id}.html")}
""".strip()
                read1_expr = trim_r1

            align_bam = shell_quote(f"align/{sample_id}.sorted.bam")
            align_block = self._alignment_block(pipeline, reference, threads, paired, read1_expr, read2_expr, align_bam)

            dedup_input = align_bam
            dedup_bam = shell_quote(f"dedup/{sample_id}.dedup.bam")
            markdup_block = ""
            if pipeline["mark_duplicates"]["enabled"]:
                markdup_block = f"""
mkdir -p dedup
picard MarkDuplicates \\
  I={align_bam} \\
  O={dedup_bam} \\
  M={shell_quote(f"dedup/{sample_id}.markdup.metrics.txt")} \\
  REMOVE_DUPLICATES=false \\
  VALIDATION_STRINGENCY=SILENT
samtools index {dedup_bam}
""".strip()
                dedup_input = dedup_bam

            peak_input = dedup_input
            blacklist_block = ""
            if pipeline["blacklist_filter"]["enabled"]:
                filtered_bam = shell_quote(f"filtered/{sample_id}.blacklist_filtered.bam")
                blacklist_block = f"""
mkdir -p filtered
bedtools intersect \\
  -v \\
  -abam {dedup_input} \\
  -b {shell_quote(reference["blacklist_bed_path"])} \\
  > {filtered_bam}
samtools index {filtered_bam}
""".strip()
                peak_input = filtered_bam

            bigwig_block = ""
            if pipeline["bigwig"]["enabled"]:
                bigwig_block = f"""
mkdir -p bigwig
bamCoverage \\
  -b {peak_input} \\
  -o {shell_quote(f"bigwig/{sample_id}.bw")} \\
  --binSize 10 \\
  --normalizeUsing CPM \\
  -p {threads}
""".strip()

            peak_block = ""
            if pipeline["peak_calling"]["enabled"]:
                peak_block = self._peak_calling_block(config, sample, peak_input, paired)

            blocks = [fastp_block, align_block, markdup_block, blacklist_block, bigwig_block, peak_block]
            rendered = "\n\n".join(block for block in blocks if block)
            sample_blocks.append(f"# Sample {shell_quote(sample_id)}\n{rendered}")

        sample_section = "\n\n".join(sample_blocks)
        env_setup_line = "source scripts/env_setup.sh" if server.get("init_commands") else ""
        prefix = f"{env_setup_line}\n\n" if env_setup_line else ""
        return f"""#!/usr/bin/env bash
set -euo pipefail

WORKDIR={shell_quote(config['server']['remote_workdir'])}
mkdir -p "$WORKDIR"/{{logs,scripts,status,fastp,align,dedup,filtered,bigwig,peaks,qc}}
cd "$WORKDIR"

cleanup_failure() {{
  echo "failed" > status/state.txt
  date -Is > status/ended_at.txt
  touch status/failed.flag
}}
trap cleanup_failure ERR

echo "running" > status/state.txt
date -Is > status/started_at.txt

{prefix}{sample_section}

echo "completed" > status/state.txt
date -Is > status/ended_at.txt
touch status/completed.flag
"""

    def _alignment_block(
        self,
        pipeline: dict[str, Any],
        reference: dict[str, Any],
        threads: int,
        paired: bool,
        read1_expr: str,
        read2_expr: str,
        align_bam: str,
    ) -> str:
        aligner = pipeline["alignment"].get("tool", "bowtie2")
        mkdir = "mkdir -p align"
        if aligner == "bwa":
            reads = f"{read1_expr} {read2_expr}" if paired else read1_expr
            return f"""
{mkdir}
bwa mem \\
  -t {threads} \\
  {shell_quote(reference["bwa_index_prefix"])} \\
  {reads} \\
  | samtools view -@ {threads} -bS - \\
  | samtools sort -@ {threads} -o {align_bam} -
samtools index {align_bam}
""".strip()

        read_args = f"-1 {read1_expr} -2 {read2_expr}" if paired else f"-U {read1_expr}"
        return f"""
{mkdir}
bowtie2 \\
  -p {threads} \\
  -x {shell_quote(reference["bowtie2_index_prefix"])} \\
  {read_args} \\
  | samtools view -@ {threads} -bS - \\
  | samtools sort -@ {threads} -o {align_bam} -
samtools index {align_bam}
""".strip()

    def _peak_calling_block(self, config: dict[str, Any], sample: dict[str, Any], peak_input: str, paired: bool) -> str:
        reference = config["reference"]
        peak_cfg = config["pipeline"]["peak_calling"]
        sample_id = sample["sample_id"]
        peak_type = peak_cfg.get("peak_type", self.default_peak_type)
        extra_args = peak_cfg.get("extra_args", self.macs_extra_args)
        broad_flag = " --broad" if peak_type == "broad" else ""
        format_flag = "BAMPE" if paired else "BAM"
        return f"""
mkdir -p peaks
macs2 callpeak \\
  -t {peak_input} \\
  -f {format_flag} \\
  -g {shell_quote(str(reference["genome_size"]))} \\
  -n {shell_quote(sample_id)} \\
  --outdir peaks{broad_flag} {extra_args}
""".strip()

    def _render_nfcore_script(self, config: dict[str, Any]) -> str:
        server = config["server"]
        nfcore = config.get("execution", {}).get("nfcore", {})
        samplesheet = self._nfcore_samplesheet(config)
        params = dict(nfcore.get("params") or {})
        if config.get("reference", {}).get("nfcore_genome"):
            params.setdefault("genome", config["reference"]["nfcore_genome"])

        revision = nfcore.get("revision")
        revision_arg = f" -r {shell_quote(revision)}" if revision else ""
        extra_args = nfcore.get("extra_args", "")
        env_setup_line = "source scripts/env_setup.sh" if server.get("init_commands") else ""
        prefix = f"{env_setup_line}\n\n" if env_setup_line else ""
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
{samplesheet}
CSV

{command}

echo "completed" > status/state.txt
date -Is > status/ended_at.txt
touch status/completed.flag
"""

    def _nfcore_samplesheet(self, config: dict[str, Any]) -> str:
        rows = []
        remote_data_dir = config["samples"]["remote_data_dir"]
        paired = config.get("sequencing", {}).get("layout", "paired") == "paired"
        for sample in config["samples"]["items"]:
            rows.append(self._nfcore_row(sample, remote_data_dir, paired))

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue().strip()

    def _nfcore_row(self, sample: dict[str, Any], remote_data_dir: str, paired: bool) -> dict[str, Any]:
        fastq_2 = remote_path(remote_data_dir, sample.get("fastq_2", "")) if paired else ""
        return {
            "sample": sample["sample_id"],
            "fastq_1": remote_path(remote_data_dir, sample["fastq_1"]),
            "fastq_2": fastq_2,
            "replicate": sample.get("replicate", 1),
        }


class ATACSeqWorkflow(EpigenomeWorkflow):
    name = "atacseq"
    label = "ATAC-seq"
    nfcore_pipeline = "nf-core/atacseq"
    nfcore_revision = "2.1.2"
    nfcore_samplesheet_type = "atacseq"
    macs_extra_args = "--nomodel --shift -100 --extsize 200"


class ChIPSeqWorkflow(EpigenomeWorkflow):
    name = "chipseq"
    label = "ChIP-seq"
    nfcore_pipeline = "nf-core/chipseq"
    nfcore_revision = "2.1.0"
    nfcore_samplesheet_type = "chipseq"

    def _nfcore_row(self, sample: dict[str, Any], remote_data_dir: str, paired: bool) -> dict[str, Any]:
        fastq_2 = remote_path(remote_data_dir, sample.get("fastq_2", "")) if paired else ""
        return {
            "sample": sample["sample_id"],
            "fastq_1": remote_path(remote_data_dir, sample["fastq_1"]),
            "fastq_2": fastq_2,
            "replicate": sample.get("replicate", 1),
            "antibody": sample.get("antibody", ""),
            "control": sample.get("control", ""),
            "control_replicate": sample.get("control_replicate", ""),
        }


class CUTTagWorkflow(EpigenomeWorkflow):
    name = "cuttag"
    label = "CUT&Tag"
    nfcore_pipeline = "nf-core/cutandrun"
    nfcore_revision = "3.2.2"
    nfcore_samplesheet_type = "cutandrun"
    macs_extra_args = "--keep-dup all"

    def default_pipeline(self) -> dict[str, Any]:
        pipeline = super().default_pipeline()
        pipeline["peak_calling"]["tool"] = "macs2"
        pipeline["seacr"] = {"enabled": False, "version": "SEACR 1.3", "mode": "stringent"}
        return pipeline

    def _nfcore_row(self, sample: dict[str, Any], remote_data_dir: str, paired: bool) -> dict[str, Any]:
        fastq_2 = remote_path(remote_data_dir, sample.get("fastq_2", "")) if paired else ""
        return {
            "group": sample.get("group", sample["sample_id"]),
            "replicate": sample.get("replicate", 1),
            "fastq_1": remote_path(remote_data_dir, sample["fastq_1"]),
            "fastq_2": fastq_2,
            "control": sample.get("control", ""),
        }
