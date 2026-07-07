# SYSU RNA-seq Agent 使用文档

本文档说明如何从本地 FASTQ 数据开始，使用 `rnaseq_agent` 上传数据到服务器、提交 RNA-seq 分析、轮询任务状态、下载结果，并在完成或失败时发送邮件提醒。

## 1. 工作流程

当前 agent 的主流程是：

```text
交互式配置 -> 校验本地 FASTQ -> 上传到服务器 -> 生成远程分析脚本 -> 提交任务 -> 定期轮询 -> 下载结果 -> 邮件提醒
```

分析流程包括：

- `fastp 0.24.1`
- `STAR 2.7.11b`
- `Arriba 2.5.0`
- `Subread / featureCounts 2.1.1`
- `RSEM 1.2.28`

默认参考文件使用 GENCODE Human Release 47 / GRCh38.p14 / ALL。

## 2. 使用前准备

本地需要：

- Python 3.11 或更高版本
- 可以执行 `ssh` 和 `scp`
- 本地 FASTQ 文件已经准备好
- 本机可以免密或正常登录目标服务器

服务器需要：

- `bash`
- `tar`
- `fastp`
- `STAR`
- `arriba`
- `featureCounts`
- `rsem-calculate-expression`
- `slurm`、`pbs` 或允许后台 shell 运行任务

服务器上还需要提前准备好参考文件和索引：

- GTF: `gencode.v47.chr_patch_hapl_scaff.annotation.gtf`
- FASTA: `GRCh38.p14.genome.fa`
- STAR index 目录
- RSEM index prefix
- 可选：Arriba blacklist / known fusions 文件

如果服务器需要先加载环境，例如 `module load` 或 `conda activate`，在向导的 `服务器初始化命令` 中填写。

示例：

```text
module load fastp STAR subread rsem arriba
```

或：

```text
source ~/miniconda3/etc/profile.d/conda.sh; conda activate rnaseq
```

多个命令用英文分号 `;` 分隔。

## 3. 启动 agent

进入项目目录：

```powershell
cd D:\code\sysuComicAgent
```

未安装时，先设置 `PYTHONPATH`：

```powershell
$env:PYTHONPATH = "src"
```

启动交互式向导：

```powershell
python -m rnaseq_agent gui
```

如果已经执行过：

```powershell
python -m pip install -e .
```

也可以使用：

```powershell
rnaseq-agent gui
```

`gui` 是推荐给普通用户使用的图形界面入口。它会用标签页收集项目、服务器、本地 FASTQ、样本、分析步骤、轮询和邮件提醒配置，最后保存生成 `project.json`。

GUI 底部提供：

- `保存配置`：只生成 `project.json`
- `校验配置`：检查 FASTQ 和关键配置
- `估算耗时`：显示预计分析时间
- `保存并运行`：保存配置后直接上传、提交、轮询、下载
- `仅提交`：保存配置并提交任务，但不等待完成
- `刷新状态`：根据当前配置刷新远程状态

如果当前环境没有图形界面，可以使用命令行对话入口：

```powershell
python -m rnaseq_agent chat
```

`chat` 会逐步询问信息、给出示例、确认摘要并生成 `project.json`。

旧版表单式入口仍然保留：

```powershell
python -m rnaseq_agent wizard
```

## 4. 第一次配置固定参考

第一次运行 `wizard` 时，会让你确认默认参考配置。

默认配置会保存到：

```text
C:\Users\zhaoq\.sysu_rnaseq_agent\defaults.json
```

这里保存的是不需要每个项目重复填写的内容，例如：

- GENCODE release
- genome FASTA 下载地址
- GTF 下载地址
- 服务器参考目录
- 服务器 GTF 路径
- 服务器 FASTA 路径
- STAR index 目录
- RSEM index prefix
- Arriba 参考文件路径

如果服务器上的参考文件路径和默认值不同，请编辑这个文件，或第一次向导时选择不使用默认配置并手动填写。

## 5. 创建项目配置

向导会逐步询问以下信息：

1. 项目基本信息
2. 服务器信息
3. 测序信息
4. 本地 FASTQ 数据
5. 分析流程步骤
6. 轮询设置
7. 邮件提醒
8. 保存配置

完成后会生成：

```text
D:\code\sysuComicAgent\runs\<project_id>\project.json
```

示例：

```text
D:\code\sysuComicAgent\runs\rnaseq_lung_cancer_001\project.json
```

## 6. 配置项说明

项目配置中的关键字段如下。

`server`：

```json
{
  "host": "your.server.edu",
  "user": "username",
  "remote_base_dir": "/data/users/username/rnaseq_projects",
  "remote_workdir": "/data/users/username/rnaseq_projects/rnaseq_demo_001",
  "scheduler": "slurm",
  "threads": 16,
  "memory_gb": 64,
  "init_commands": []
}
```

`samples`：

```json
{
  "source": "local_upload",
  "local_data_dir": "D:/data/rnaseq/raw_fastq",
  "remote_data_dir": "/data/users/username/rnaseq_projects/rnaseq_demo_001/raw",
  "items": [
    {
      "sample_id": "Ctrl_1",
      "condition": "control",
      "fastq_1": "Ctrl_1_R1.fastq.gz",
      "fastq_2": "Ctrl_1_R2.fastq.gz"
    }
  ]
}
```

`reference`：

```json
{
  "remote_gtf_path": "/data/ref/gencode/human/release_47_all/gencode.v47.chr_patch_hapl_scaff.annotation.gtf",
  "remote_genome_fasta_path": "/data/ref/gencode/human/release_47_all/GRCh38.p14.genome.fa",
  "star_index_dir": "/data/ref/gencode/human/release_47_all/star_2.7.11b",
  "rsem_index_prefix": "/data/ref/gencode/human/release_47_all/rsem/rsem_gencode_v47"
}
```

`polling`：

```json
{
  "interval_seconds": 300,
  "timeout_hours": 168
}
```

`notification`：

```json
{
  "email_enabled": true,
  "recipient": "user@example.com",
  "smtp_host": "smtp.example.com",
  "smtp_port": 587,
  "smtp_user": "user@example.com",
  "password_env": "RNASEQ_AGENT_SMTP_PASSWORD"
}
```

邮件密码不会写入配置文件，需要放到环境变量。

PowerShell 示例：

```powershell
$env:RNASEQ_AGENT_SMTP_PASSWORD = "your_email_auth_code"
```

## 7. 分析前检查

检查本地 FASTQ 是否存在：

```powershell
python -m rnaseq_agent validate-local runs\<project_id>\project.json
```

如果通过，会显示：

```text
Checked FASTQ files: 4
Local FASTQ validation passed.
```

如果失败，会列出缺失文件或配置错误。

查看预计耗时：

```powershell
python -m rnaseq_agent estimate runs\<project_id>\project.json
```

查看将要执行的上传命令：

```powershell
python -m rnaseq_agent upload-command runs\<project_id>\project.json
```

## 8. 一键运行分析

确认配置无误后，执行：

```powershell
python -m rnaseq_agent run runs\<project_id>\project.json
```

这个命令会自动完成：

1. 校验本地 FASTQ
2. 在服务器创建项目目录和 raw 目录
3. 上传 FASTQ 到服务器
4. 生成远程分析脚本
5. 上传脚本到服务器
6. 通过 `slurm` / `pbs` / 远程后台 shell 提交任务
7. 定期轮询任务状态
8. 完成后打包并下载结果
9. 发送邮件提醒

默认情况下，`run` 会一直等待任务结束。

如果只想提交任务，不等待完成：

```powershell
python -m rnaseq_agent run runs\<project_id>\project.json --no-wait
```

## 9. 查看任务状态

如果使用 `--no-wait` 提交，后续可以手动刷新状态：

```powershell
python -m rnaseq_agent status runs\<project_id>\project.json
```

状态会写回：

```text
runs\<project_id>\project.json
```

常见状态：

- `configured`
- `validated`
- `uploaded`
- `submitted`
- `queued`
- `running`
- `completed`
- `remote_completed`
- `download_failed`
- `failed`
- `timeout`
- `run_failed`

## 10. 输出文件位置

本地项目目录：

```text
runs\<project_id>\
```

主要文件：

```text
runs\<project_id>\project.json
runs\<project_id>\generated_scripts\
runs\<project_id>\generated_scripts\env_setup.sh
runs\<project_id>\generated_scripts\run_pipeline.sh
runs\<project_id>\agent_logs\
runs\<project_id>\downloads\downloads_bundle.tar.gz
runs\<project_id>\downloads\extracted\
```

服务器项目目录：

```text
<remote_base_dir>/<project_id>/
```

典型远程目录结构：

```text
raw/
scripts/
logs/
status/
fastp/
star/
arriba/
featurecounts/
rsem/
downloads_bundle.tar.gz
```

下载结果默认是一个压缩包：

```text
runs\<project_id>\downloads\downloads_bundle.tar.gz
```

agent 会自动解压到：

```text
runs\<project_id>\downloads\extracted\
```

## 11. 服务器调度器设置

`server.scheduler` 支持：

- `slurm`
- `pbs`
- `local`

`slurm` 会执行：

```bash
sbatch --parsable scripts/submit.sbatch
```

`pbs` 会执行：

```bash
qsub scripts/submit.pbs
```

`local` 会执行：

```bash
nohup bash scripts/submit.sh > logs/local-run.out 2>&1 < /dev/null &
```

如果服务器没有调度系统，可以先选 `local`。

## 12. 常见问题

### 12.1 FASTQ 文件不存在

现象：

```text
Missing FASTQ files:
```

处理：

- 检查 `samples.local_data_dir`
- 检查 `fastq_1` 和 `fastq_2` 文件名
- 确认文件名大小写一致

### 12.2 SSH 连接失败

现象：

```text
Could not resolve hostname
Permission denied
Connection timed out
```

处理：

- 检查 `server.host`
- 检查 `server.user`
- 先手动测试：

```powershell
ssh username@your.server.edu
```

### 12.3 服务器找不到工具

现象：

```text
fastp: command not found
STAR: command not found
featureCounts: command not found
```

处理：

- 在 `server.init_commands` 中加入 `module load` 或 `conda activate`
- 手动登录服务器确认工具是否在 `PATH`

### 12.4 参考文件路径错误

现象：

```text
No such file or directory
```

处理：

- 检查 `reference.remote_gtf_path`
- 检查 `reference.remote_genome_fasta_path`
- 检查 `reference.star_index_dir`
- 检查 `reference.rsem_index_prefix`

### 12.5 邮件没有发送

处理：

- 确认 `notification.email_enabled` 是 `true`
- 确认 SMTP 配置正确
- 确认已设置密码环境变量：

```powershell
$env:RNASEQ_AGENT_SMTP_PASSWORD = "your_email_auth_code"
```

## 13. 推荐使用顺序

第一次使用：

```powershell
cd D:\code\sysuComicAgent
$env:PYTHONPATH = "src"
python -m rnaseq_agent gui
python -m rnaseq_agent validate-local runs\<project_id>\project.json
python -m rnaseq_agent estimate runs\<project_id>\project.json
python -m rnaseq_agent run runs\<project_id>\project.json
```

日常使用：

```powershell
cd D:\code\sysuComicAgent
$env:PYTHONPATH = "src"
python -m rnaseq_agent gui
python -m rnaseq_agent run runs\<project_id>\project.json
```

如果使用 GUI，也可以不手动执行 `run`，直接点击窗口底部的 `保存并运行`。

## 14. Agent 和传统软件的区别

这个项目有 GUI，但不只是传统桌面软件。区别在于：

- GUI 只是一个入口，背后仍然生成明确的 `project.json` 配置。
- 每次运行都会留下脚本、日志、状态和下载结果，便于审计和复现。
- 同一套执行引擎同时支持 GUI、命令行对话和 CLI。
- 它负责编排本地数据、服务器上传、远程提交、轮询、下载和通知，而不是只在本机点按钮。
- 后续可以继续扩展到其他分析流程，例如 ATAC-seq、ChIP-seq、单细胞等，而不需要推翻交互方式。

提交后不等待：

```powershell
python -m rnaseq_agent run runs\<project_id>\project.json --no-wait
python -m rnaseq_agent status runs\<project_id>\project.json
```
