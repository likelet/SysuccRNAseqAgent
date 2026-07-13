# SysuccOmicAgent Workflow Backends

SysuccOmicAgent supports multiple workflow types through `workflow.type`.

## Registered Workflows

| `workflow.type` | Label | Default backend | Optional nf-core pipeline |
| --- | --- | --- | --- |
| `rnaseq` | Bulk RNA-seq | `bash` | `nf-core/rnaseq` |
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

## RNA-seq Reference Auto-Setup

The RNA-seq bash backend can prepare the default GENCODE reference on the server when files are missing. The default reference is GENCODE Human Release 47, GRCh38.p14, ALL regions.

Controlled fields:

- `reference.auto_setup`: enable or disable server-side preparation.
- `reference.gtf_url`: compressed GTF download URL.
- `reference.genome_fasta_url`: compressed genome FASTA download URL.
- `reference.remote_gtf_path`: decompressed GTF target path on the server.
- `reference.remote_genome_fasta_path`: decompressed FASTA target path on the server.
- `reference.star_index_dir`: STAR genome index target directory.
- `reference.rsem_index_prefix`: RSEM reference prefix.

When `auto_setup` is true, `run_pipeline.sh` checks the configured paths. Missing FASTA/GTF files are downloaded with `curl` or `wget`, STAR index is generated with `STAR --runMode genomeGenerate`, and RSEM reference is generated with `rsem-prepare-reference` when RSEM is enabled.

## Example Configs

- `examples/project.demo.json`
- `examples/project.rnaseq.nfcore.demo.json`
- `examples/project.atacseq.demo.json`
- `examples/project.chipseq.demo.json`
- `examples/project.cuttag.demo.json`
