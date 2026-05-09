"""Debug CLI for the RPA harness."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from .errors import RPAError
from .registry import discover_providers
from .runner import run_workflow_file
from .workflow import load_workflow

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command("list-providers")
def list_providers() -> None:
    registry = discover_providers()
    for manifest in registry.manifests():
        typer.echo(json.dumps(manifest.to_dict(), ensure_ascii=False))


@app.command("validate-workflow")
def validate_workflow_cmd(path: Path) -> None:
    try:
        workflow = load_workflow(path)
    except RPAError as exc:
        typer.echo(f"invalid workflow: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"ok: {workflow['id']}")


@app.command("run-workflow")
def run_workflow_cmd(
    path: Path,
    provider: str | None = typer.Option(None, "--provider"),
    input_json: str | None = typer.Option(None, "--inputs", help="JSON object of workflow inputs."),
) -> None:
    inputs: dict[str, Any] = {}
    if input_json:
        try:
            parsed = json.loads(input_json)
        except json.JSONDecodeError as exc:
            typer.echo(f"invalid --inputs JSON: {exc}", err=True)
            raise typer.Exit(1) from exc
        if not isinstance(parsed, dict):
            typer.echo("--inputs must be a JSON object", err=True)
            raise typer.Exit(1)
        inputs = parsed
    try:
        result = run_workflow_file(path, provider_name=provider, inputs=inputs)
    except RPAError as exc:
        typer.echo(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), err=True)
        raise typer.Exit(1) from exc
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
