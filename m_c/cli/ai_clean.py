"""Click command for verified AI-image metadata cleanup."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from m_c.core.ai_cleaner import (
    AIImageCleaner,
    AIImageCleanerError,
    collect_ai_images,
)


def _output_path(
    source_root: Path,
    input_path: Path,
    output: str | None,
) -> Path:
    if output:
        requested = Path(output).expanduser()
        if source_root.is_file():
            return requested.resolve()
        relative = input_path.resolve().relative_to(source_root.resolve())
        return (requested / relative).resolve()

    if source_root.is_file():
        root = source_root.parent / "cleaned-ai"
        return (root / source_root.name).resolve()
    relative = input_path.resolve().relative_to(source_root.resolve())
    return (source_root / "cleaned-ai" / relative).resolve()


def _non_overwriting_path(path: Path, input_path: Path) -> Path:
    if path.resolve() == input_path.resolve():
        raise AIImageCleanerError("Output path must differ from input path.")
    if not path.exists():
        return path
    counter = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _summary_status(summary: dict[str, Any]) -> str:
    if summary["total"] == 0:
        return "unsupported_input"
    if summary["succeeded"] == summary["total"]:
        return "success"
    if summary["succeeded"] == 0:
        return "failure"
    return "partial_failure"


def _write_summary(path: str | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


@click.command(name="ai-clean")
@click.argument("path", type=click.Path(exists=True, path_type=str))
@click.option(
    "--output",
    default=None,
    help="Output file for one input, or output directory for a batch.",
)
@click.option(
    "--privacy-transform",
    is_flag=True,
    help="Force same-format re-encoding to change the binary file hash.",
)
@click.option(
    "--dry-run", is_flag=True, help="List supported images without writing files."
)
@click.option(
    "--json-summary", is_flag=True, help="Print the machine-readable summary."
)
@click.option(
    "--summary-file",
    type=click.Path(dir_okay=False, path_type=str),
    default=None,
    help="Write the machine-readable summary to a file.",
)
@click.option("--quiet", is_flag=True, help="Suppress human-readable progress output.")
@click.pass_context
def ai_clean(
    ctx: click.Context,
    path: str,
    output: str | None,
    privacy_transform: bool,
    dry_run: bool,
    json_summary: bool,
    summary_file: str | None,
    quiet: bool,
) -> None:
    """Remove embedded image metadata and verify the cleaned copies."""

    source_root = Path(path).resolve()
    files = [Path(item).resolve() for item in collect_ai_images(source_root)]
    summary: dict[str, Any] = {
        "status": "unsupported_input",
        "mode": "deep",
        "privacy_transform": privacy_transform,
        "source": str(source_root),
        "total": len(files),
        "succeeded": 0,
        "failed": 0,
        "files": [],
        "failures": [],
    }

    if not files:
        summary["error"] = "No supported image files found."
        _write_summary(summary_file, summary)
        if json_summary:
            click.echo(json.dumps(summary, indent=2, sort_keys=True))
        elif not quiet:
            click.echo(summary["error"])
        ctx.exit(2)

    if dry_run:
        summary["status"] = "success"
        summary["would_process"] = [str(item) for item in files]
        summary["succeeded"] = len(files)
        for item in files:
            planned = _non_overwriting_path(
                _output_path(source_root, item, output),
                item,
            )
            summary["files"].append(
                {
                    "input": str(item),
                    "output": str(planned),
                    "status": "would_process",
                }
            )
        _write_summary(summary_file, summary)
        if json_summary:
            click.echo(json.dumps(summary, indent=2, sort_keys=True))
        elif not quiet:
            click.echo(f"Dry run: {len(files)} image(s) would be cleaned.")
        ctx.exit(0)

    try:
        cleaner = AIImageCleaner()
    except AIImageCleanerError as exc:
        summary["error"] = str(exc)
        summary["failed"] = len(files)
        summary["status"] = "dependency_error"
        _write_summary(summary_file, summary)
        if json_summary:
            click.echo(json.dumps(summary, indent=2, sort_keys=True))
        elif not quiet:
            click.echo(f"Dependency error: {exc}")
        ctx.exit(2)

    for input_path in files:
        target = _non_overwriting_path(
            _output_path(source_root, input_path, output),
            input_path,
        )
        try:
            result = cleaner.clean(
                input_path,
                target,
                privacy_transform=privacy_transform,
            )
            summary["succeeded"] += 1
            item = result.to_dict()
            item["status"] = "success"
            summary["files"].append(item)
            if not quiet and not json_summary:
                click.echo(f"Cleaned and verified: {input_path} -> {target}")
        except Exception as exc:
            summary["failed"] += 1
            summary["failures"].append(str(input_path))
            summary["files"].append(
                {
                    "input": str(input_path),
                    "output": str(target),
                    "status": "failed",
                    "error": str(exc),
                }
            )
            if not quiet and not json_summary:
                click.echo(f"Failed: {input_path}: {exc}")

    summary["status"] = _summary_status(summary)
    _write_summary(summary_file, summary)
    if json_summary:
        click.echo(json.dumps(summary, indent=2, sort_keys=True))
    elif not quiet:
        click.echo(
            "Summary: "
            f"succeeded={summary['succeeded']}, "
            f"failed={summary['failed']}, total={summary['total']}"
        )

    if summary["status"] == "success":
        ctx.exit(0)
    if summary["status"] == "failure":
        ctx.exit(1)
    ctx.exit(3)
