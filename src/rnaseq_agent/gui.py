from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from tkinter import BooleanVar, StringVar, Text, Tk, filedialog, messagebox
from tkinter import ttk
from typing import Any

from .configuration import normalize_config
from .defaults import DEFAULT_PIPELINE, DEFAULT_REFERENCE
from .estimate import estimate_runtime
from .remote import project_remote_workdir
from .run_agent import refresh_status, run_project
from .storage import load_defaults, save_defaults, save_json
from .validation import validate_local_fastqs


class ConfigApp(Tk):
    def __init__(self, output_dir: Path) -> None:
        super().__init__()
        self.output_dir = output_dir
        self.title("SysuccOmicAgent")
        self.geometry("1040x740")
        self.minsize(920, 640)
        self.running = False
        self.current_config_path: Path | None = None

        saved = load_defaults()
        self.reference_defaults = saved["reference"] if saved else DEFAULT_REFERENCE.copy()

        self.project_id = StringVar(value=f"rnaseq_{datetime.now():%Y%m%d_%H%M%S}")
        self.project_title = StringVar(value=self.project_id.get())
        self.owner = StringVar(value="local_user")

        self.server_profile = StringVar(value="sysu_hpc")
        self.server_host = StringVar(value="your.server.edu")
        self.server_user = StringVar(value="username")
        self.remote_base_dir = StringVar(value="/data/users/username/rnaseq_projects")
        self.scheduler = StringVar(value="slurm")
        self.threads = StringVar(value="16")
        self.memory_gb = StringVar(value="64")

        self.layout = StringVar(value="paired")
        self.reads_per_sample_million = StringVar(value="40")
        self.strandedness = StringVar(value="auto")
        self.local_data_dir = StringVar(value="D:/data/rnaseq/raw_fastq")
        self.remote_data_dir = StringVar(value="AUTO")

        self.ref_vars = {key: StringVar(value=str(value)) for key, value in self.reference_defaults.items()}
        self.pipeline_vars = {
            step: BooleanVar(value=bool(config["enabled"])) for step, config in DEFAULT_PIPELINE.items()
        }

        self.poll_interval = StringVar(value="300")
        self.poll_timeout = StringVar(value="168")

        self.email_enabled = BooleanVar(value=True)
        self.recipient = StringVar(value="user@example.com")
        self.smtp_host = StringVar(value="smtp.example.com")
        self.smtp_port = StringVar(value="587")
        self.smtp_user = StringVar(value="user@example.com")
        self.smtp_password_env = StringVar(value="RNASEQ_AGENT_SMTP_PASSWORD")

        self.status_text = StringVar(value="填写配置后，可以保存、校验、直接运行或仅提交。")
        self.sample_text: Text
        self.init_text: Text

        self._build_ui()

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)

        ttk.Label(
            root,
            text="填写 RNA-seq 分析配置。保存后会生成 project.json，也可以直接点击“保存并运行”。",
        ).pack(anchor="w", pady=(0, 8))

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)
        notebook.add(self._project_tab(notebook), text="项目")
        notebook.add(self._server_tab(notebook), text="服务器")
        notebook.add(self._reference_tab(notebook), text="参考")
        notebook.add(self._samples_tab(notebook), text="样本")
        notebook.add(self._pipeline_tab(notebook), text="流程")
        notebook.add(self._notification_tab(notebook), text="通知")

        footer = ttk.Frame(root)
        footer.pack(fill="x", pady=(10, 0))
        ttk.Label(footer, textvariable=self.status_text).pack(side="left", fill="x", expand=True)
        ttk.Button(footer, text="刷新状态", command=self.refresh_project_status).pack(side="right", padx=(6, 0))
        ttk.Button(footer, text="仅提交", command=lambda: self.start_run(wait=False)).pack(side="right", padx=(6, 0))
        ttk.Button(footer, text="保存并运行", command=lambda: self.start_run(wait=True)).pack(side="right", padx=(6, 0))
        ttk.Button(footer, text="估算耗时", command=self.show_estimate).pack(side="right", padx=(6, 0))
        ttk.Button(footer, text="校验配置", command=self.validate_form).pack(side="right", padx=(6, 0))
        ttk.Button(footer, text="保存配置", command=self.save_config).pack(side="right", padx=(6, 0))

    def _project_tab(self, parent: ttk.Notebook) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=16)
        self._entry(frame, "项目 ID", self.project_id, 0, "例如 rnaseq_lung_cancer_001")
        self._entry(frame, "项目名称", self.project_title, 1)
        self._entry(frame, "负责人/用户", self.owner, 2)
        return frame

    def _server_tab(self, parent: ttk.Notebook) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=16)
        self._entry(frame, "服务器配置名", self.server_profile, 0)
        self._entry(frame, "服务器地址 host", self.server_host, 1, "例如 hpc.example.edu")
        self._entry(frame, "服务器用户名", self.server_user, 2)
        self._entry(frame, "服务器项目根目录", self.remote_base_dir, 3)
        self._combo(frame, "调度器", self.scheduler, ["slurm", "pbs", "local"], 4)
        self._entry(frame, "线程数", self.threads, 5)
        self._entry(frame, "内存 GB", self.memory_gb, 6)
        ttk.Label(frame, text="服务器初始化命令").grid(row=7, column=0, sticky="nw", pady=5)
        self.init_text = Text(frame, height=5, width=76)
        self.init_text.grid(row=7, column=1, sticky="nsew", pady=5)
        ttk.Label(frame, text="例如：module load STAR fastp subread rsem arriba").grid(row=8, column=1, sticky="w")
        frame.columnconfigure(1, weight=1)
        return frame

    def _reference_tab(self, parent: ttk.Notebook) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=16)
        fields = [
            ("参考配置名", "name"),
            ("服务器 GTF 路径", "remote_gtf_path"),
            ("服务器 genome FASTA 路径", "remote_genome_fasta_path"),
            ("STAR index 目录", "star_index_dir"),
            ("RSEM index prefix", "rsem_index_prefix"),
            ("Arriba blacklist 路径", "arriba_blacklist_path"),
            ("Arriba known fusions 路径", "arriba_known_fusions_path"),
        ]
        for row, (label, key) in enumerate(fields):
            self._entry(frame, label, self.ref_vars[key], row)
        ttk.Button(frame, text="保存为默认参考配置", command=self.save_reference_defaults).grid(
            row=len(fields), column=1, sticky="e", pady=(10, 0)
        )
        return frame

    def _samples_tab(self, parent: ttk.Notebook) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=16)
        self._combo(frame, "测序类型", self.layout, ["paired", "single"], 0)
        self._entry(frame, "reads/样本，单位 M", self.reads_per_sample_million, 1)
        self._combo(frame, "链特异性", self.strandedness, ["auto", "unstranded", "forward", "reverse"], 2)
        self._entry(frame, "本地 FASTQ 目录", self.local_data_dir, 3)
        ttk.Button(frame, text="选择目录", command=self.choose_fastq_dir).grid(row=3, column=2, padx=(6, 0))
        self._entry(frame, "服务器接收 FASTQ 目录", self.remote_data_dir, 4, "填 AUTO 则使用 <项目目录>/raw")

        ttk.Label(frame, text="样本表：sample_id, condition, fastq_1, fastq_2").grid(
            row=5, column=0, columnspan=3, sticky="w", pady=(12, 4)
        )
        self.sample_text = Text(frame, height=12, width=90)
        self.sample_text.grid(row=6, column=0, columnspan=3, sticky="nsew")
        self.sample_text.insert(
            "1.0",
            "Ctrl_1,control,Ctrl_1_R1.fastq.gz,Ctrl_1_R2.fastq.gz\n"
            "Treat_1,treatment,Treat_1_R1.fastq.gz,Treat_1_R2.fastq.gz\n",
        )
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(6, weight=1)
        return frame

    def _pipeline_tab(self, parent: ttk.Notebook) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=16)
        for row, (step, config) in enumerate(DEFAULT_PIPELINE.items()):
            ttk.Checkbutton(frame, text=f"{step} ({config['version']})", variable=self.pipeline_vars[step]).grid(
                row=row, column=0, sticky="w", pady=4
            )
        self._entry(frame, "轮询间隔秒数", self.poll_interval, len(DEFAULT_PIPELINE) + 1)
        self._entry(frame, "最长等待小时数", self.poll_timeout, len(DEFAULT_PIPELINE) + 2)
        return frame

    def _notification_tab(self, parent: ttk.Notebook) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=16)
        ttk.Checkbutton(frame, text="启用邮件通知", variable=self.email_enabled).grid(row=0, column=1, sticky="w", pady=5)
        self._entry(frame, "接收邮箱", self.recipient, 1)
        self._entry(frame, "SMTP 服务器", self.smtp_host, 2)
        self._entry(frame, "SMTP 端口", self.smtp_port, 3)
        self._entry(frame, "SMTP 用户名", self.smtp_user, 4)
        self._entry(frame, "SMTP 密码环境变量名", self.smtp_password_env, 5)
        ttk.Label(frame, text="密码/授权码不写入配置文件，请放在环境变量中。").grid(row=6, column=1, sticky="w")
        return frame

    def _entry(self, frame: ttk.Frame, label: str, variable: StringVar, row: int, hint: str = "") -> None:
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(frame, textvariable=variable, width=72).grid(row=row, column=1, sticky="ew", pady=5)
        if hint:
            ttk.Label(frame, text=hint).grid(row=row, column=2, sticky="w", padx=(8, 0))
        frame.columnconfigure(1, weight=1)

    def _combo(self, frame: ttk.Frame, label: str, variable: StringVar, values: list[str], row: int) -> None:
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Combobox(frame, textvariable=variable, values=values, state="readonly", width=20).grid(
            row=row, column=1, sticky="w", pady=5
        )

    def choose_fastq_dir(self) -> None:
        directory = filedialog.askdirectory(title="选择本地 FASTQ 目录")
        if directory:
            self.local_data_dir.set(directory.replace("\\", "/"))

    def build_config(self) -> dict[str, Any]:
        project_id = self.project_id.get().strip()
        if not project_id:
            raise ValueError("项目 ID 不能为空。")

        remote_workdir = project_remote_workdir(self.remote_base_dir.get().strip(), project_id)
        remote_data_dir = self.remote_data_dir.get().strip()
        if remote_data_dir == "AUTO":
            remote_data_dir = f"{remote_workdir}/raw"

        config = {
            "schema_version": 1,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "project": {
                "id": project_id,
                "title": self.project_title.get().strip() or project_id,
                "owner": self.owner.get().strip() or "local_user",
            },
            "server": {
                "profile": self.server_profile.get().strip(),
                "host": self.server_host.get().strip(),
                "user": self.server_user.get().strip(),
                "remote_base_dir": self.remote_base_dir.get().strip(),
                "remote_workdir": remote_workdir,
                "scheduler": self.scheduler.get(),
                "threads": int(self.threads.get()),
                "memory_gb": int(self.memory_gb.get()),
                "shell": "bash",
                "init_commands": self._parse_init_commands(),
            },
            "reference": self.collect_reference(),
            "sequencing": {
                "layout": self.layout.get(),
                "reads_per_sample_million": int(self.reads_per_sample_million.get()),
                "strandedness": self.strandedness.get(),
            },
            "samples": {
                "source": "local_upload",
                "local_data_dir": self.local_data_dir.get().strip(),
                "remote_data_dir": remote_data_dir,
                "items": self._parse_samples(),
            },
            "pipeline": {
                step: {"enabled": bool(var.get()), "version": DEFAULT_PIPELINE[step]["version"]}
                for step, var in self.pipeline_vars.items()
            },
            "polling": {"interval_seconds": int(self.poll_interval.get()), "timeout_hours": int(self.poll_timeout.get())},
            "notification": self._notification_config(),
            "status": {"state": "configured", "message": "Project config created by GUI mode."},
        }
        config = normalize_config(config)
        runtime = estimate_runtime(config)
        config["runtime_estimate"] = {"hours": runtime.hours, "summary": runtime.summary}
        return config

    def collect_reference(self) -> dict[str, Any]:
        reference = DEFAULT_REFERENCE.copy()
        for key, variable in self.ref_vars.items():
            reference[key] = variable.get().strip()
        return reference

    def _parse_init_commands(self) -> list[str]:
        text = self.init_text.get("1.0", "end").strip()
        if not text:
            return []
        commands: list[str] = []
        for line in text.splitlines():
            commands.extend(part.strip() for part in line.split(";") if part.strip())
        return commands

    def _parse_samples(self) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        paired = self.layout.get() == "paired"
        for raw_line in self.sample_text.get("1.0", "end").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 3:
                raise ValueError(f"样本行至少需要 3 列：{line}")
            items.append(
                {
                    "sample_id": parts[0],
                    "condition": parts[1],
                    "fastq_1": parts[2],
                    "fastq_2": parts[3] if paired and len(parts) > 3 else "",
                }
            )
        return items

    def _notification_config(self) -> dict[str, Any]:
        if not self.email_enabled.get():
            return {"email_enabled": False}
        return {
            "email_enabled": True,
            "recipient": self.recipient.get().strip(),
            "smtp_host": self.smtp_host.get().strip(),
            "smtp_port": int(self.smtp_port.get()),
            "smtp_user": self.smtp_user.get().strip(),
            "password_env": self.smtp_password_env.get().strip(),
            "notify_on": ["completed", "failed", "download_failed", "run_failed"],
        }

    def save_reference_defaults(self) -> None:
        save_defaults({"reference": self.collect_reference()})
        messagebox.showinfo("已保存", "默认参考配置已保存。")

    def save_config(self) -> Path | None:
        try:
            config_path = self.save_config_silent()
        except Exception as exc:
            messagebox.showerror("配置错误", str(exc))
            return None
        messagebox.showinfo("保存成功", f"配置已保存：\n{config_path}")
        return config_path

    def save_config_silent(self) -> Path:
        config = self.build_config()
        config_path = self.output_dir / config["project"]["id"] / "project.json"
        save_json(config_path, config)
        self.current_config_path = config_path
        self.status_text.set(f"配置已保存：{config_path}")
        return config_path

    def validate_form(self) -> None:
        try:
            config = self.build_config()
            result = validate_local_fastqs(config)
        except Exception as exc:
            messagebox.showerror("配置错误", str(exc))
            return
        if result.ok:
            messagebox.showinfo("校验通过", "本地 FASTQ 和配置校验通过。")
            return
        lines = []
        lines.extend(result.errors)
        lines.extend(str(path) for path in result.missing_files[:12])
        if len(result.missing_files) > 12:
            lines.append(f"还有 {len(result.missing_files) - 12} 个缺失文件未显示。")
        messagebox.showwarning("校验未通过", "\n".join(lines) or "校验未通过。")

    def show_estimate(self) -> None:
        try:
            runtime = estimate_runtime(self.build_config())
        except Exception as exc:
            messagebox.showerror("配置错误", str(exc))
            return
        messagebox.showinfo("预计耗时", runtime.summary)

    def start_run(self, wait: bool) -> None:
        if self.running:
            messagebox.showinfo("正在运行", "已有任务正在运行，请等待当前任务结束。")
            return
        try:
            config_path = self.save_config_silent()
        except Exception as exc:
            messagebox.showerror("配置错误", str(exc))
            return
        self.running = True
        mode = "运行并等待完成" if wait else "提交后返回"
        self.status_text.set(f"已启动：{mode}，配置 {config_path}")
        threading.Thread(target=self._run_worker, args=(config_path, wait), daemon=True).start()

    def _run_worker(self, config_path: Path, wait: bool) -> None:
        try:
            outcome = run_project(config_path, wait=wait)
        except Exception as exc:
            self.after(0, self._run_finished, False, str(exc), config_path)
            return
        self.after(0, self._run_finished, True, outcome.message, config_path)

    def _run_finished(self, ok: bool, message: str, config_path: Path) -> None:
        self.running = False
        self.current_config_path = config_path
        self.status_text.set(message)
        if ok:
            messagebox.showinfo("任务状态", message)
        else:
            messagebox.showerror("任务失败", message)

    def refresh_project_status(self) -> None:
        config_path = self.current_config_path
        if config_path is None:
            try:
                config_path = self.save_config_silent()
            except Exception as exc:
                messagebox.showerror("配置错误", str(exc))
                return

        def worker() -> None:
            try:
                status = refresh_status(config_path)
                state = status.get("state", "unknown")
                message = status.get("message", "")
                text = f"{state}: {message}" if message else state
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("刷新状态失败", str(exc)))
                return
            self.after(0, lambda: self.status_text.set(text))

        threading.Thread(target=worker, daemon=True).start()


def run_gui(output_dir: Path) -> None:
    app = ConfigApp(output_dir)
    app.mainloop()
