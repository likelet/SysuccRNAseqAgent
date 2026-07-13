from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .configuration import normalize_config
from .defaults import DEFAULT_PIPELINE, DEFAULT_REFERENCE
from .estimate import estimate_runtime
from .remote import project_remote_workdir
from .storage import load_defaults, save_defaults, save_json
from .validation import validate_local_fastqs


class ChatSession:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    def run(self) -> Path:
        self.say("你好，我是 SysuccOmicAgent。")
        self.say("我会像问诊一样一步步收集配置，最后生成 project.json。")
        self.say("提示：直接回车使用默认值；输入 ? 查看当前问题说明；输入 quit 退出。")
        self.say("")

        reference = self.collect_reference()
        project = self.collect_project()
        server = self.collect_server(project["id"])
        sequencing = self.collect_sequencing()
        samples = self.collect_samples(project["id"], server, sequencing)
        pipeline = self.collect_pipeline()
        polling = self.collect_polling()
        notification = self.collect_notification()

        remote_workdir = project_remote_workdir(server["remote_base_dir"], project["id"])
        if samples["remote_data_dir"] == "AUTO":
            samples["remote_data_dir"] = f"{remote_workdir}/raw"

        config = normalize_config(
            {
                "schema_version": 1,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "project": project,
                "server": {**server, "remote_workdir": remote_workdir},
                "reference": reference,
                "sequencing": sequencing,
                "samples": samples,
                "pipeline": pipeline,
                "polling": polling,
                "notification": notification,
                "status": {
                    "state": "configured",
                    "message": "Project config created by chat mode.",
                },
            }
        )

        runtime = estimate_runtime(config)
        config["runtime_estimate"] = {"hours": runtime.hours, "summary": runtime.summary}

        self.show_summary(config, runtime.summary)
        if not self.ask_yes_no("以上配置是否确认保存？", default=True, help_text="选择 n 会退出且不写入 project.json。"):
            raise SystemExit("已取消保存。")

        config_path = self.output_dir / project["id"] / "project.json"
        save_json(config_path, config)
        self.say("")
        self.say(f"配置已保存：{config_path}")
        self.say(runtime.summary)

        validation = validate_local_fastqs(config)
        if validation.ok:
            self.say("本地 FASTQ 初步校验通过。下一步可以运行：")
        else:
            self.say("注意：当前配置还没有通过本地 FASTQ 校验。你可以先修改配置或补齐文件。")
            for error in validation.errors:
                self.say(f"- 配置错误：{error}")
            for path in validation.missing_files[:8]:
                self.say(f"- 缺失文件：{path}")
            if len(validation.missing_files) > 8:
                self.say(f"- 还有 {len(validation.missing_files) - 8} 个缺失文件未显示")
            self.say("修正后再运行：")

        self.say(f"python -m rnaseq_agent validate-local {config_path}")
        self.say(f"python -m rnaseq_agent run {config_path}")
        return config_path

    def collect_reference(self) -> dict[str, Any]:
        self.section(1, "固定参考配置")
        saved = load_defaults()
        if saved:
            reference = saved["reference"]
            self.say(f"已找到默认参考配置：{reference['name']}")
            if self.ask_yes_no("是否继续使用这份默认参考配置？", default=True):
                return reference

        self.say("默认使用 GENCODE Human Release 47 / GRCh38.p14 / ALL。")
        self.say(f"GTF: {DEFAULT_REFERENCE['gtf_url']}")
        self.say(f"FASTA: {DEFAULT_REFERENCE['genome_fasta_url']}")
        if self.ask_yes_no("是否使用默认参考配置？", default=True):
            save_defaults({"reference": DEFAULT_REFERENCE})
            return DEFAULT_REFERENCE.copy()

        reference = DEFAULT_REFERENCE.copy()
        reference["name"] = self.ask("参考配置名", reference["name"], "例如 GENCODE_R47_GRCh38p14_ALL")
        reference["remote_gtf_path"] = self.ask(
            "服务器上的 GTF 文件路径",
            reference["remote_gtf_path"],
            "例如 /data/ref/gencode/human/release_47_all/gencode.v47...annotation.gtf",
        )
        reference["remote_genome_fasta_path"] = self.ask(
            "服务器上的 genome FASTA 路径",
            reference["remote_genome_fasta_path"],
            "例如 /data/ref/gencode/human/release_47_all/GRCh38.p14.genome.fa",
        )
        reference["star_index_dir"] = self.ask("STAR index 目录", reference["star_index_dir"])
        reference["rsem_index_prefix"] = self.ask("RSEM index prefix", reference["rsem_index_prefix"])
        reference["arriba_blacklist_path"] = self.ask("Arriba blacklist 路径，可留空", reference["arriba_blacklist_path"])
        reference["arriba_known_fusions_path"] = self.ask(
            "Arriba known fusions 路径，可留空",
            reference["arriba_known_fusions_path"],
        )
        save_defaults({"reference": reference})
        return reference

    def collect_project(self) -> dict[str, str]:
        self.section(2, "项目基本信息")
        project_id = self.ask("项目 ID", f"rnaseq_{datetime.now():%Y%m%d_%H%M%S}", "建议只用英文、数字和下划线。")
        title = self.ask("项目名称", project_id, "可写中文，用于自己识别项目。")
        owner = self.ask("负责人/用户", "local_user")
        return {"id": project_id, "title": title, "owner": owner}

    def collect_server(self, project_id: str) -> dict[str, Any]:
        self.section(3, "服务器信息")
        profile = self.ask("服务器配置名", "sysu_hpc")
        host = self.ask("服务器地址 host", "your.server.edu", "例如 hpc.example.edu。")
        user = self.ask("服务器用户名", "username")
        remote_base_dir = self.ask(
            "服务器项目根目录",
            f"/data/users/{user}/rnaseq_projects",
            f"本项目会放到 <根目录>/{project_id}。",
        )
        scheduler = self.ask_choice("服务器调度器", ["slurm", "pbs", "local"], "slurm")
        threads = self.ask_int("每个任务线程数", 16)
        memory_gb = self.ask_int("内存 GB", 64)
        init_commands = self.ask_list(
            "服务器初始化命令",
            "",
            "如 module load STAR fastp subread rsem arriba；多个命令用 ; 分隔；没有就回车。",
        )
        return {
            "profile": profile,
            "host": host,
            "user": user,
            "remote_base_dir": remote_base_dir,
            "scheduler": scheduler,
            "threads": threads,
            "memory_gb": memory_gb,
            "shell": "bash",
            "init_commands": init_commands,
        }

    def collect_sequencing(self) -> dict[str, Any]:
        self.section(4, "测序信息")
        layout = self.ask_choice("测序类型", ["paired", "single"], "paired")
        reads = self.ask_int("每个样本 reads 数量估计，单位 M", 40)
        strandedness = self.ask_choice("链特异性", ["auto", "unstranded", "forward", "reverse"], "auto")
        return {
            "layout": layout,
            "reads_per_sample_million": reads,
            "strandedness": strandedness,
        }

    def collect_samples(self, project_id: str, server: dict[str, Any], sequencing: dict[str, Any]) -> dict[str, Any]:
        self.section(5, "本地 FASTQ 和样本信息")
        local_data_dir = self.ask("本地 FASTQ 目录", "D:/data/rnaseq/raw_fastq")
        default_remote = f"{project_remote_workdir(server['remote_base_dir'], project_id)}/raw"
        remote_data_dir = self.ask("服务器接收 FASTQ 目录", default_remote)

        paired = sequencing["layout"] == "paired"
        self.say("接下来逐个录入样本。样本录入完成后，在样本 ID 处直接回车结束。")
        self.say("示例：Ctrl_1 / control / Ctrl_1_R1.fastq.gz / Ctrl_1_R2.fastq.gz")
        items: list[dict[str, str]] = []
        index = 1
        while True:
            sample_id = self.ask(f"样本 {index} ID", "" if items else f"sample_{index}")
            if not sample_id:
                if items:
                    break
                self.say("至少需要 1 个样本。")
                continue
            condition = self.ask(f"{sample_id} 分组/条件", "control" if index == 1 else "treatment")
            fastq_1 = self.ask(f"{sample_id} FASTQ R1", f"{sample_id}_R1.fastq.gz")
            sample = {
                "sample_id": sample_id,
                "condition": condition,
                "fastq_1": fastq_1,
            }
            if paired:
                sample["fastq_2"] = self.ask(f"{sample_id} FASTQ R2", f"{sample_id}_R2.fastq.gz")
            else:
                sample["fastq_2"] = ""
            items.append(sample)
            index += 1

        return {
            "source": "local_upload",
            "local_data_dir": local_data_dir,
            "remote_data_dir": remote_data_dir,
            "items": items,
        }

    def collect_pipeline(self) -> dict[str, Any]:
        self.section(6, "分析步骤")
        pipeline = {}
        for step, cfg in DEFAULT_PIPELINE.items():
            enabled = self.ask_yes_no(f"是否启用 {step} ({cfg['version']})？", default=cfg["enabled"])
            pipeline[step] = {"enabled": enabled, "version": cfg["version"]}
        return pipeline

    def collect_polling(self) -> dict[str, Any]:
        self.section(7, "轮询设置")
        interval_seconds = self.ask_int("每隔多少秒检查一次任务状态", 300)
        timeout_hours = self.ask_int("最多等待多少小时", 168)
        return {"interval_seconds": interval_seconds, "timeout_hours": timeout_hours}

    def collect_notification(self) -> dict[str, Any]:
        self.section(8, "邮件提醒")
        enabled = self.ask_yes_no("分析完成或失败时是否邮件提醒？", default=True)
        if not enabled:
            return {"email_enabled": False}
        recipient = self.ask("接收邮箱", "user@example.com")
        smtp_host = self.ask("SMTP 服务器", "smtp.example.com")
        smtp_port = self.ask_int("SMTP 端口", 587)
        smtp_user = self.ask("SMTP 用户名", recipient)
        password_env = self.ask("SMTP 密码环境变量名", "RNASEQ_AGENT_SMTP_PASSWORD")
        return {
            "email_enabled": True,
            "recipient": recipient,
            "smtp_host": smtp_host,
            "smtp_port": smtp_port,
            "smtp_user": smtp_user,
            "password_env": password_env,
            "notify_on": ["completed", "failed", "download_failed", "run_failed"],
        }

    def show_summary(self, config: dict[str, Any], estimate_summary: str) -> None:
        self.section(9, "配置确认")
        self.say(f"项目：{config['project']['id']} ({config['project']['title']})")
        self.say(f"服务器：{config['server']['user']}@{config['server']['host']}")
        self.say(f"远程目录：{config['server']['remote_workdir']}")
        self.say(f"本地 FASTQ 目录：{config['samples']['local_data_dir']}")
        self.say(f"样本数量：{len(config['samples']['items'])}")
        self.say(f"调度器：{config['server']['scheduler']}，线程：{config['server']['threads']}，内存：{config['server']['memory_gb']}G")
        enabled_steps = [name for name, step in config["pipeline"].items() if step.get("enabled")]
        self.say(f"启用步骤：{', '.join(enabled_steps)}")
        self.say(estimate_summary)

    def section(self, index: int, title: str) -> None:
        self.say("")
        self.say(f"[{index}/9] {title}")

    def say(self, message: str) -> None:
        print(message)

    def ask(self, prompt: str, default: str, help_text: str = "") -> str:
        while True:
            suffix = f" [{default}]" if default else ""
            value = input(f"{prompt}{suffix}: ").strip()
            if value.lower() == "quit":
                raise SystemExit("已退出。")
            if value == "?":
                self.say(help_text or "直接输入答案；如果有默认值，回车会使用默认值。")
                continue
            return value or default

    def ask_int(self, prompt: str, default: int, help_text: str = "") -> int:
        while True:
            value = self.ask(prompt, str(default), help_text)
            try:
                return int(value)
            except ValueError:
                self.say("这里需要填写整数。")

    def ask_yes_no(self, prompt: str, default: bool, help_text: str = "") -> bool:
        default_text = "Y/n" if default else "y/N"
        while True:
            value = input(f"{prompt} [{default_text}]: ").strip().lower()
            if value == "quit":
                raise SystemExit("已退出。")
            if value == "?":
                self.say(help_text or "请输入 y 或 n；直接回车使用默认值。")
                continue
            if not value:
                return default
            if value in {"y", "yes", "是"}:
                return True
            if value in {"n", "no", "否"}:
                return False
            self.say("请输入 y 或 n。")

    def ask_choice(self, prompt: str, choices: list[str], default: str) -> str:
        choices_text = "/".join(choices)
        while True:
            value = self.ask(f"{prompt} ({choices_text})", default, f"可选值：{choices_text}")
            if value in choices:
                return value
            self.say(f"请输入以下选项之一：{choices_text}")

    def ask_list(self, prompt: str, default: str, help_text: str = "") -> list[str]:
        text = self.ask(prompt, default, help_text)
        if not text:
            return []
        return [item.strip() for item in text.split(";") if item.strip()]


def run_chat(output_dir: Path) -> Path:
    return ChatSession(output_dir).run()
