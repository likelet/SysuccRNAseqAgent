from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .configuration import normalize_config
from .emailer import send_completion_email
from .execution import CommandResult, run_command
from .remote import build_upload_commands
from .shell import shell_quote
from .storage import append_jsonl, load_json, save_json
from .validation import validate_local_fastqs
from .workflows import get_workflow


@dataclass(frozen=True)
class RunOutcome:
    state: str
    message: str
    project_dir: Path


def run_project(config_path: Path, *, wait: bool = True) -> RunOutcome:
    config = normalize_config(load_json(config_path))
    save_json(config_path, config)
    project_dir = config_path.parent
    logs_dir = project_dir / "agent_logs"
    downloads_dir = project_dir / "downloads"
    logs_dir.mkdir(parents=True, exist_ok=True)
    downloads_dir.mkdir(parents=True, exist_ok=True)

    _log_event(logs_dir, "run_started", {"config": str(config_path)})
    try:
        validation = validate_local_fastqs(config)
        if not validation.ok:
            parts = []
            if validation.missing_files:
                parts.append(f"{len(validation.missing_files)} files missing")
            if validation.errors:
                parts.append("; ".join(validation.errors))
            message = "Local FASTQ validation failed: " + ", ".join(parts)
            _update_status(config_path, "validation_failed", message)
            _log_event(
                logs_dir,
                "validation_failed",
                {
                    "missing_files": [str(path) for path in validation.missing_files],
                    "errors": validation.errors,
                },
            )
            raise RuntimeError(message)

        _update_status(config_path, "validated", "Local FASTQ validation passed.")
        _upload_fastqs(config, logs_dir)
        _update_status(config_path, "uploaded", "Local FASTQ files uploaded to the server.")

        remote_scripts = _prepare_remote_scripts(config, project_dir, logs_dir)
        _upload_support_files(config, remote_scripts, logs_dir)
        submit_result = _submit_remote_job(config, logs_dir)
        job_id = submit_result.stdout.strip() or "submitted"

        config = normalize_config(load_json(config_path))
        config["status"] = {
            "state": "submitted",
            "message": "Remote analysis job submitted.",
            "job_id": job_id,
            "submitted_at": datetime.now().isoformat(timespec="seconds"),
        }
        save_json(config_path, config)
        _log_event(logs_dir, "submitted", {"job_id": job_id, "stdout": submit_result.stdout.strip()})

        if not wait:
            return RunOutcome("submitted", f"Job submitted: {job_id}", project_dir)

        final_state = _poll_until_finished(config_path, logs_dir)
        if final_state == "completed":
            _update_status(config_path, "remote_completed", "Remote RNA-seq analysis completed.")
            try:
                _download_results(normalize_config(load_json(config_path)), downloads_dir, logs_dir)
            except Exception as download_exc:
                message = f"Remote analysis completed, but downloading results failed: {download_exc}"
                _update_status(config_path, "download_failed", message)
                _notify(normalize_config(load_json(config_path)), "download_failed", message)
                return RunOutcome("download_failed", message, project_dir)
            message = "RNA-seq analysis completed and results downloaded."
            final_state = "completed"
        elif final_state == "timeout":
            message = "RNA-seq analysis did not finish before the polling timeout."
        else:
            message = "RNA-seq analysis failed on the server."

        _update_status(config_path, final_state, message)
        _notify(normalize_config(load_json(config_path)), final_state, message)
        return RunOutcome(final_state, message, project_dir)
    except Exception as exc:
        message = str(exc)
        _update_status(config_path, "run_failed", message)
        _log_event(logs_dir, "run_failed", {"message": message})
        try:
            _notify(normalize_config(load_json(config_path)), "run_failed", message)
        except Exception as notify_exc:
            _log_event(logs_dir, "notify_failed", {"message": str(notify_exc)})
        raise


def refresh_status(config_path: Path) -> dict[str, Any]:
    config = normalize_config(load_json(config_path))
    state = _read_remote_state(config)
    if state:
        message = f"Remote state: {state}"
        _update_status(config_path, state, message)
    return normalize_config(load_json(config_path)).get("status", {})


def _upload_fastqs(config: dict[str, Any], logs_dir: Path) -> None:
    for command in build_upload_commands(config):
        result = run_command(command.command)
        _log_command(logs_dir, command.description, result)


def _prepare_remote_scripts(config: dict[str, Any], project_dir: Path, logs_dir: Path) -> list[Path]:
    scripts_dir = project_dir / "generated_scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    env_setup_script = scripts_dir / "env_setup.sh"
    workflow = get_workflow(config)
    env_setup_script.write_text(workflow.render_env_setup_script(config), encoding="utf-8", newline="\n")

    run_script = scripts_dir / "run_pipeline.sh"
    run_script.write_text(workflow.render_pipeline_script(config), encoding="utf-8", newline="\n")

    submit_name = "submit.sh"
    scheduler = config["server"]["scheduler"]
    if scheduler == "slurm":
        submit_name = "submit.sbatch"
    elif scheduler == "pbs":
        submit_name = "submit.pbs"
    submit_script = scripts_dir / submit_name
    submit_script.write_text(workflow.render_submit_script(config), encoding="utf-8", newline="\n")

    rendered_paths = [env_setup_script, run_script, submit_script]
    _log_event(logs_dir, "scripts_rendered", {"paths": [str(path) for path in rendered_paths]})
    return rendered_paths


def _upload_support_files(config: dict[str, Any], paths: list[Path], logs_dir: Path) -> None:
    server = config["server"]
    target = f"{server['user']}@{server['host']}"
    remote_workdir = server["remote_workdir"]

    result = run_command(
        [
            "ssh",
            target,
            (
                f"mkdir -p {shell_quote(remote_workdir + '/scripts')} "
                f"{shell_quote(remote_workdir + '/logs')} "
                f"{shell_quote(remote_workdir + '/status')}"
            ),
        ]
    )
    _log_command(logs_dir, "Create remote work directories", result)

    scp_args = ["scp", *(str(path).replace("\\", "/") for path in paths), f"{target}:{remote_workdir.rstrip('/')}/scripts/"]
    result = run_command(scp_args)
    _log_command(logs_dir, "Upload support scripts", result)


def _submit_remote_job(config: dict[str, Any], logs_dir: Path) -> CommandResult:
    server = config["server"]
    target = f"{server['user']}@{server['host']}"
    remote_workdir = server["remote_workdir"]
    scheduler = server["scheduler"]

    if scheduler == "slurm":
        remote_cmd = f"cd {shell_quote(remote_workdir)} && sbatch --parsable scripts/submit.sbatch"
    elif scheduler == "pbs":
        remote_cmd = f"cd {shell_quote(remote_workdir)} && qsub scripts/submit.pbs"
    elif scheduler == "local":
        remote_cmd = (
            f"cd {shell_quote(remote_workdir)} && "
            "nohup bash scripts/submit.sh > logs/local-run.out 2>&1 < /dev/null & echo $!"
        )
    else:
        raise ValueError(f"Unsupported scheduler: {scheduler}")

    result = run_command(["ssh", target, remote_cmd])
    _log_command(logs_dir, "Submit remote job", result)
    return result


def _poll_until_finished(config_path: Path, logs_dir: Path) -> str:
    config = normalize_config(load_json(config_path))
    polling = config.get("polling", {})
    interval_seconds = int(polling.get("interval_seconds", 300))
    timeout_hours = float(polling.get("timeout_hours", 168))
    deadline = time.time() + timeout_hours * 3600

    while time.time() < deadline:
        state = _read_remote_state(config)
        if state:
            _update_status(config_path, state, f"Remote state: {state}")
            _log_event(logs_dir, "poll", {"state": state})
            if state in {"completed", "failed"}:
                return state
        time.sleep(interval_seconds)
        config = normalize_config(load_json(config_path))

    _log_event(logs_dir, "poll_timeout", {"timeout_hours": timeout_hours})
    return "timeout"


def _read_remote_state(config: dict[str, Any]) -> str:
    server = config["server"]
    target = f"{server['user']}@{server['host']}"
    remote_workdir = server["remote_workdir"]
    command = [
        "ssh",
        target,
        (
            f"if [ -f {shell_quote(remote_workdir + '/status/completed.flag')} ]; then echo completed; "
            f"elif [ -f {shell_quote(remote_workdir + '/status/failed.flag')} ]; then echo failed; "
            f"elif [ -f {shell_quote(remote_workdir + '/status/state.txt')} ]; then cat {shell_quote(remote_workdir + '/status/state.txt')}; "
            "else echo queued; fi"
        ),
    ]
    result = run_command(command)
    return result.stdout.strip()


def _download_results(config: dict[str, Any], downloads_dir: Path, logs_dir: Path) -> None:
    server = config["server"]
    target = f"{server['user']}@{server['host']}"
    remote_workdir = server["remote_workdir"]
    downloads_dir.mkdir(parents=True, exist_ok=True)
    remote_tar = f"{remote_workdir.rstrip('/')}/downloads_bundle.tar.gz"
    workflow = get_workflow(config)
    dirs = " ".join(workflow.result_dirs)
    pack_cmd = (
        f"cd {shell_quote(remote_workdir)} && "
        "paths=(); "
        f"for d in {dirs}; do "
        'if [ -e "$d" ]; then paths+=("$d"); fi; '
        "done; "
        f"tar -czf {shell_quote(remote_tar)} \"${{paths[@]}}\""
    )
    result = run_command(["ssh", target, pack_cmd])
    _log_command(logs_dir, "Package results on server", result)

    local_tar = downloads_dir / "downloads_bundle.tar.gz"
    result = run_command(["scp", f"{target}:{remote_tar}", str(local_tar).replace("\\", "/")])
    _log_command(logs_dir, "Download result bundle", result)
    extract_dir = downloads_dir / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)
    result = run_command(["tar", "-xzf", str(local_tar), "-C", str(extract_dir)])
    _log_command(logs_dir, "Extract result bundle locally", result)


def _notify(config: dict[str, Any], state: str, message: str) -> None:
    notification = config.get("notification", {})
    if not notification.get("email_enabled"):
        return
    subject = f"[SysuccOmicAgent] {config['project']['id']} {state}"
    body = (
        f"Project: {config['project']['id']}\n"
        f"State: {state}\n"
        f"Message: {message}\n"
        f"Remote workdir: {config['server']['remote_workdir']}\n"
    )
    send_completion_email(notification, subject, body)


def _update_status(config_path: Path, state: str, message: str) -> None:
    config = normalize_config(load_json(config_path))
    status = config.get("status", {})
    status.update(
        {
            "state": state,
            "message": message,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    config["status"] = status
    save_json(config_path, config)


def _log_event(logs_dir: Path, event: str, payload: dict[str, Any]) -> None:
    append_jsonl(
        logs_dir / "events.jsonl",
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "event": event,
            **payload,
        },
    )


def _log_command(logs_dir: Path, description: str, result: CommandResult) -> None:
    append_jsonl(
        logs_dir / "commands.jsonl",
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "description": description,
            "command": result.command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        },
    )
