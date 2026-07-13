from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .chat import run_chat
from .configuration import normalize_config
from .estimate import estimate_runtime
from .gui import run_gui
from .remote import build_directory_scan_command, build_upload_commands
from .run_agent import refresh_status, run_project
from .storage import load_json
from .validation import validate_local_fastqs
from .wizard import run_wizard


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sysucc-omic-agent",
        description="Interactive RNA-seq analysis agent.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    wizard = subparsers.add_parser("wizard", help="Start the interactive project wizard.")
    wizard.add_argument(
        "--output-dir",
        default="runs",
        help="Directory where project configs will be written. Default: runs",
    )

    chat = subparsers.add_parser("chat", help="Start the conversational project setup agent.")
    chat.add_argument(
        "--output-dir",
        default="runs",
        help="Directory where project configs will be written. Default: runs",
    )

    gui = subparsers.add_parser("gui", help="Start the graphical project setup interface.")
    gui.add_argument(
        "--output-dir",
        default="runs",
        help="Directory where project configs will be written. Default: runs",
    )

    estimate = subparsers.add_parser("estimate", help="Estimate runtime from a saved project config.")
    estimate.add_argument("config", help="Path to project.json")

    scan = subparsers.add_parser(
        "scan-command",
        help="Print an optional SSH command for checking a remote FASTQ directory.",
    )
    scan.add_argument("config", help="Path to project.json")

    upload = subparsers.add_parser(
        "upload-command",
        help="Print commands that upload local FASTQ files to the server.",
    )
    upload.add_argument("config", help="Path to project.json")

    validate = subparsers.add_parser(
        "validate-local",
        help="Check whether local FASTQ files referenced by the project config exist.",
    )
    validate.add_argument("config", help="Path to project.json")

    run = subparsers.add_parser(
        "run",
        help="Validate, upload, submit, poll, download, and optionally notify for a project.",
    )
    run.add_argument("config", help="Path to project.json")
    run.add_argument(
        "--no-wait",
        action="store_true",
        help="Submit the remote job and return without polling for completion.",
    )

    status = subparsers.add_parser(
        "status",
        help="Refresh project status from the server and print the current state.",
    )
    status.add_argument("config", help="Path to project.json")

    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "wizard":
        run_wizard(Path(args.output_dir))
        return 0

    if args.command == "chat":
        run_chat(Path(args.output_dir))
        return 0

    if args.command == "gui":
        run_gui(Path(args.output_dir))
        return 0

    if args.command == "estimate":
        config = normalize_config(load_json(Path(args.config)))
        runtime = estimate_runtime(config)
        print(runtime.summary)
        return 0

    if args.command == "scan-command":
        config = normalize_config(load_json(Path(args.config)))
        server = config["server"]
        remote_dir = config["samples"]["remote_data_dir"]
        command = build_directory_scan_command(server["host"], server["user"], remote_dir)
        print(command.description)
        print(f"{command.command[0]} {command.command[1]} \"{command.command[2]}\"")
        return 0

    if args.command == "upload-command":
        config = normalize_config(load_json(Path(args.config)))
        for command in build_upload_commands(config):
            print(command.description)
            print(_format_command(command.command))
        return 0

    if args.command == "validate-local":
        config = normalize_config(load_json(Path(args.config)))
        result = validate_local_fastqs(config)
        print(f"Checked FASTQ files: {result.checked_files}")
        if result.ok:
            print("Local FASTQ validation passed.")
            return 0
        if result.errors:
            print("Configuration errors:")
            for error in result.errors:
                print(error)
        if result.missing_files:
            print("Missing FASTQ files:")
            for path in result.missing_files:
                print(path)
        return 1

    if args.command == "run":
        try:
            outcome = run_project(Path(args.config), wait=not args.no_wait)
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(outcome.message)
        print(f"Project directory: {outcome.project_dir}")
        return 0 if outcome.state in {"submitted", "completed"} else 1

    if args.command == "status":
        status = refresh_status(Path(args.config))
        print(status.get("state", "unknown"))
        print(status.get("message", ""))
        if status.get("job_id"):
            print(f"job_id={status['job_id']}")
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


def _format_command(command: list[str]) -> str:
    return " ".join(_quote_arg(arg) for arg in command)


def _quote_arg(arg: str) -> str:
    if not arg or any(char.isspace() for char in arg):
        return '"' + arg.replace('"', '\\"') + '"'
    return arg
