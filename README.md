# SYSU RNA-seq Agent

This project starts an interactive RNA-seq analysis agent from scratch. The current version can validate local FASTQ files, upload them to a remote server, generate remote pipeline scripts for `fastp`, `STAR`, `Arriba`, `featureCounts`, and `RSEM`, submit the job through `slurm`, `pbs`, or a remote background shell, poll job state, download result bundles, and send email notifications.

Author: Qi Zhao <zhaoqi@sysucc.org.cn>

## Current Capabilities

- Interactive wizard with step-by-step progress.
- One-time default reference setup for GENCODE human release 47.
- Per-project local FASTQ, server, polling, notification, and pipeline configuration.
- Runtime estimate based on sample count, read depth, selected steps, and thread count.
- Local FASTQ validation before upload.
- Upload command generation for transferring local FASTQ files to the server.
- End-to-end `run` command for validate -> upload -> submit -> poll -> download.
- `status` command for refreshing current remote state.
- Email notification settings stored in the project config.
- JSON configuration only for now, so the tool runs with the Python standard library.

## Analysis Workflow

```mermaid
flowchart LR
    A["Local FASTQ"] --> B["Upload to server raw/"]
    B --> C["fastp 0.24.1<br/>QC and trimming"]
    C --> D["STAR 2.7.11b<br/>Genome alignment"]

    D --> E["Sorted BAM"]
    D --> F["Transcriptome BAM"]
    D --> G["Chimeric output"]
    D --> H["GeneCounts"]

    E --> I["Arriba 2.5.0<br/>Fusion detection"]
    G --> I
    I --> I1["fusions.tsv"]

    E --> J["Subread featureCounts 2.1.1<br/>Gene count matrix"]
    J --> J1["gene_counts.txt"]

    F --> K["RSEM 1.2.28<br/>Gene/transcript expression"]
    K --> K1["*.genes.results"]
    K --> K2["*.isoforms.results"]

    C --> L["fastp HTML / JSON"]
    D --> M["STAR logs"]

    I1 --> N["Result bundle"]
    J1 --> N
    K1 --> N
    K2 --> N
    L --> N
    M --> N
    N --> O["Download and extract locally"]
```

## Assumptions

- The local machine can access the server with `ssh` and `scp`.
- The server has `bash`, `tar`, and the configured RNA-seq tools in `PATH`, or can expose them through `init_commands`.
- Reference files and indexes already exist on the server and their paths are correct in the saved defaults.
- `slurm`, `pbs`, or plain remote shell execution is available, matching `server.scheduler`.

## Usage

Full Chinese usage guide: [docs/usage.md](docs/usage.md)

Project flow diagrams: [docs/flow.md](docs/flow.md)

From this repository without installation:

```powershell
$env:PYTHONPATH = "src"
python -m rnaseq_agent gui
```

Or install it in editable mode:

```powershell
python -m pip install -e .
rnaseq-agent gui
```

Recommended flow:

```powershell
$env:PYTHONPATH = "src"
python -m rnaseq_agent gui
python -m rnaseq_agent run runs/<project_id>/project.json
```

`gui` is the recommended entry for most users. It opens a desktop form, validates the fields, and writes `runs/<project_id>/project.json`.
The GUI can also run the analysis directly with "Save and Run", submit without waiting, and refresh remote status.

Use `chat` when a graphical desktop is not available. It asks questions conversationally, shows examples, confirms a summary, and writes `runs/<project_id>/project.json`.

## Agent vs Traditional Software

This project has a GUI, but its core is still an agent-style workflow:

- Configuration is stored as explicit, reusable JSON rather than hidden GUI state.
- Every run generates scripts, logs, status files, and downloadable artifacts for auditing.
- The GUI, chat mode, and CLI all drive the same execution engine.
- The analysis workflow can be extended to other pipelines without redesigning the interface.
- It orchestrates local data, remote execution, polling, download, and notification instead of only running local actions.

If you want to inspect the individual steps first:

```powershell
$env:PYTHONPATH = "src"
python -m rnaseq_agent validate-local runs/<project_id>/project.json
python -m rnaseq_agent upload-command runs/<project_id>/project.json
python -m rnaseq_agent estimate runs/<project_id>/project.json
python -m rnaseq_agent status runs/<project_id>/project.json
```

The wizard writes:

- User defaults: `%USERPROFILE%/.sysu_rnaseq_agent/defaults.json`
- Project config: `runs/<project_id>/project.json`
- Generated remote scripts: `runs/<project_id>/generated_scripts/`
- Agent logs: `runs/<project_id>/agent_logs/`
- Downloaded bundle: `runs/<project_id>/downloads/downloads_bundle.tar.gz`
- Extracted results: `runs/<project_id>/downloads/extracted/`

## RNA-seq Reference Defaults

The default reference follows the requested GENCODE Human Release 47 files:

- GTF: `gencode.v47.chr_patch_hapl_scaff.annotation.gtf.gz`
- FASTA: `GRCh38.p14.genome.fa.gz`
- Assembly: `GRCh38.p14`
- Region set: `ALL`

`ALL` matches the screenshot selection and includes reference chromosomes, scaffolds, assembly patches, and alternate loci. For smaller routine expression workflows, a future preset can add the primary assembly option.

## Notes

- For HPC environments that require `module load` or `conda activate`, fill `server.init_commands` in the wizard.
- `run` blocks until completion by default. Use `--no-wait` to return after submission:

```powershell
$env:PYTHONPATH = "src"
python -m rnaseq_agent run runs/<project_id>/project.json --no-wait
```

- The downloaded result is saved as a `.tar.gz` bundle and automatically extracted under `downloads/extracted/`.

## Planned Next Steps

1. Add checksum recording before and after upload.
2. Add a native `claw` backend as an alternative to `ssh` and `scp`.
3. Add local result interpretation and Markdown report generation.
4. Add more explicit tool-path and container configuration.
