# SysuccOmicAgent Workflow Backends

SysuccOmicAgent supports multiple workflow types through `workflow.type`.

## Registered Workflows

| `workflow.type` | Label | Default backend | Optional nf-core pipeline |
| --- | --- | --- | --- |
| `rnaseq` | Bulk RNA-seq | `bash` | Not wired in this version |
| `atacseq` | ATAC-seq | `bash` | `nf-core/atacseq` |
| `chipseq` | ChIP-seq | `bash` | `nf-core/chipseq` |
| `cuttag` | CUT&Tag | `bash` | `nf-core/cutandrun` |

## Bash Backend

The bash backend renders `run_pipeline.sh` directly from the project config. For ATAC-seq, ChIP-seq, and CUT&Tag, the generated script can use:

- `fastp` for read QC and trimming.
- `bowtie2` or `bwa` for genome alignment.
- `samtools` for BAM conversion, sorting, and indexing.
- `picard MarkDuplicates` for duplicate metrics and duplicate marking.
- `bedtools` for optional blacklist filtering.
- `bamCoverage` from deepTools for bigWig generation.
- `macs2` for peak calling.

Server-specific module loading or conda activation should be placed in `server.init_commands`.

## nf-core Backend

The nf-core backend renders a Nextflow command and a workflow-specific samplesheet on the server. Enable it with:

```json
{
  "execution": {
    "backend": "nfcore",
    "nfcore": {
      "pipeline": "nf-core/atacseq",
      "revision": "2.1.2",
      "profile": "singularity",
      "params": {},
      "extra_args": ""
    }
  }
}
```

Use `execution.nfcore.params` for pipeline parameters such as custom genome settings, aligner settings, or peak-calling flags. Use `execution.nfcore.extra_args` for Nextflow-level flags that do not belong in `params`.

The server must provide `nextflow`, Java, and the selected container/runtime profile such as Singularity, Apptainer, Docker, or Conda.

## Example Configs

- `examples/project.demo.json`
- `examples/project.atacseq.demo.json`
- `examples/project.chipseq.demo.json`
- `examples/project.cuttag.demo.json`
