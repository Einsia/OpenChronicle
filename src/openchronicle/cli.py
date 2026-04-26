"""OpenChronicle CLI — start / stop / pause / resume / status / mcp / writer."""

from __future__ import annotations

import contextlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import __version__, paths
from . import config as config_mod
from . import logger as logger_mod
from .store import entries as entries_mod
from .store import fts, index_md

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Local-first screen-context memory for LLM agents.",
)
console = Console()


def _init() -> config_mod.Config:
    paths.ensure_dirs()
    created = config_mod.write_default_if_missing()
    if created:
        console.print(f"[green]Created default config at {paths.config_file()}[/green]")
    logger_mod.setup(console=False)
    return config_mod.load()


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if platform.system() == "Windows":
        return _is_pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _is_pid_alive_windows(pid: int) -> bool:
    import ctypes

    kernel32 = ctypes.windll.kernel32
    process_query_limited_information = 0x1000
    still_active = 259
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        error_access_denied = 5
        return kernel32.GetLastError() == error_access_denied
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _read_pid() -> int | None:
    try:
        pid = int(paths.pid_file().read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None
    return pid if _is_pid_alive(pid) else None


def _daemon_uptime() -> str:
    """Return a human-readable uptime string for the running daemon.

    Reads the PID file's mtime as a proxy for daemon start time (the
    daemon overwrites it on each launch). Returns ``"stopped"`` when
    the daemon is not running.
    """
    pid = _read_pid()
    if not pid:
        return "stopped"
    try:
        mtime = paths.pid_file().stat().st_mtime
        now = datetime.now().astimezone()
        delta = now - datetime.fromtimestamp(mtime).astimezone()
        h, r = divmod(int(delta.total_seconds()), 3600)
        m = r // 60
        if h >= 24:
            return f"{h // 24}d {h % 24}h"
        if h:
            return f"{h}h {m}m"
        return f"{m}m"
    except OSError:
        return "unknown"


def _last_capture_info() -> tuple[str | None, str | None]:
    """Return ``(timestamp, app_name)`` of the most recent capture buffer file.

    Returns ``(None, None)`` when the buffer directory is empty or missing.
    """
    buf = paths.capture_buffer_dir()
    if not buf.exists():
        return None, None
    json_files = sorted(p for p in buf.iterdir() if p.suffix == ".json")
    if not json_files:
        return None, None
    try:
        data = json.loads(json_files[-1].read_bytes())
        ts = data.get("timestamp")
        meta = data.get("window_meta") or {}
        app = meta.get("app_name")
        return ts, app
    except (OSError, ValueError):
        return json_files[-1].stem, None


def _health_status(pid: int | None, last_ts: str | None) -> tuple[str, str]:
    """Return ``(label, style)`` for daemon health.

    ``style`` is a Rich-style string suitable for ``console.print``.
    """
    if not pid:
        return "stopped", "red"
    if not last_ts:
        return "running (no captures yet)", "yellow"
    try:
        last = datetime.fromisoformat(last_ts)
        age = (datetime.now(last.tzinfo) - last).total_seconds()
    except (ValueError, TypeError):
        return "running", "green"
    if age < 300:  # 5 minutes
        return "healthy", "green"
    return "stale (no captures in >5m)", "yellow"


def _wait_for_pid(timeout: float = 5.0) -> int | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pid = _read_pid()
        if pid:
            return pid
        time.sleep(0.1)
    return _read_pid()


def _start_background_windows(*, capture_only: bool) -> int | None:
    cmd = [sys.executable, "-m", "openchronicle.cli", "start", "--foreground"]
    if capture_only:
        cmd.append("--capture-only")

    creationflags = 0
    for name in ("CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS", "CREATE_NO_WINDOW"):
        creationflags |= getattr(subprocess, name, 0)

    subprocess.Popen(  # noqa: S603
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creationflags,
    )
    return _wait_for_pid()


def _start_background_posix(cfg: config_mod.Config, *, capture_only: bool) -> None:
    from . import daemon

    if os.fork() != 0:
        console.print("[green]OpenChronicle started in background.[/green]")
        console.print(f"Logs: {paths.logs_dir()}")
        return
    os.setsid()
    if os.fork() != 0:
        os._exit(0)
    # Redirect stdio to /dev/null. After dup2 the original fd is no longer
    # needed; closing it avoids leaking one descriptor per daemon start.
    devnull = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(devnull, fd)
    if devnull > 2:
        os.close(devnull)
    daemon.run(cfg, capture_only=capture_only)
    os._exit(0)


def _remove_stale_pid() -> None:
    with contextlib.suppress(FileNotFoundError):
        paths.pid_file().unlink()


# ─── commands ─────────────────────────────────────────────────────────────

@app.command()
def start(
    foreground: bool = typer.Option(False, "--foreground", "-f", help="Run in this terminal."),
    capture_only: bool = typer.Option(False, "--capture-only", help="Skip the writer loop."),
) -> None:
    """Start the OpenChronicle daemon."""
    cfg = _init()
    pid = _read_pid()
    if pid:
        console.print(f"[yellow]Already running (pid {pid})[/yellow]")
        raise typer.Exit(1)
    if paths.pid_file().exists():
        _remove_stale_pid()

    from . import daemon

    if foreground:
        console.print("[bold]OpenChronicle starting in foreground[/bold] — Ctrl+C to stop.")
        daemon.run(cfg, capture_only=capture_only)
        return

    if platform.system() == "Windows":
        started_pid = _start_background_windows(capture_only=capture_only)
        console.print("[green]OpenChronicle started in background.[/green]")
        console.print(f"Logs: {paths.logs_dir()}")
        if started_pid:
            console.print(f"PID: {started_pid}")
        return

    _start_background_posix(cfg, capture_only=capture_only)


@app.command()
def stop() -> None:
    """Stop the daemon."""
    _init()
    pid = _read_pid()
    if not pid:
        console.print("[yellow]Daemon not running.[/yellow]")
        raise typer.Exit(1)
    os.kill(pid, signal.SIGTERM)
    console.print(f"[green]Sent SIGTERM to pid {pid}.[/green]")
    if platform.system() == "Windows":
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and _is_pid_alive(pid):
            time.sleep(0.1)
        if not _is_pid_alive(pid):
            _remove_stale_pid()


@app.command()
def pause() -> None:
    """Pause capture (daemon stays up but skips captures)."""
    paths.ensure_dirs()
    paths.paused_flag().write_text(datetime.now().isoformat(), encoding="utf-8")
    console.print("[yellow]Capture paused.[/yellow]")


@app.command()
def resume() -> None:
    """Resume capture."""
    with contextlib.suppress(FileNotFoundError):
        paths.paused_flag().unlink()
    console.print("[green]Capture resumed.[/green]")


@app.command()
def status() -> None:
    """Show daemon status + memory stats."""
    cfg = _init()
    pid = _read_pid()
    paused = paths.paused_flag().exists()

    uptime = _daemon_uptime()
    last_ts, last_app = _last_capture_info()
    health_label, health_style = _health_status(pid, last_ts)

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_row("Version", __version__)
    table.add_row("Root", str(paths.root()))
    table.add_row("Daemon", f"[green]running pid {pid}[/green]" if pid else "[red]stopped[/red]")
    table.add_row("Uptime", uptime)
    table.add_row("Health", f"[{health_style}]{health_label}[/{health_style}]")
    table.add_row("Capture", "[yellow]paused[/yellow]" if paused else "active")

    if last_ts:
        try:
            last_dt = datetime.fromisoformat(last_ts)
            age = (datetime.now(last_dt.tzinfo) - last_dt).total_seconds()
            if age < 60:
                ago = "just now"
            elif age < 3600:
                ago = f"{int(age // 60)}m ago"
            else:
                ago = f"{int(age // 3600)}h ago"
            table.add_row("Last Capture", f"{ago} ({last_app})" if last_app else ago)
        except (ValueError, TypeError):
            table.add_row("Last Capture", last_ts)
    else:
        table.add_row("Last Capture", "(none)")

    buf = paths.capture_buffer_dir()
    if buf.exists():
        bufs = sorted(p for p in buf.iterdir() if p.suffix == ".json")
        last = bufs[-1].name if bufs else "(none)"
        table.add_row("Buffer", f"{len(bufs)} files, last: {last}")

    with fts.cursor() as conn:
        sess_row = conn.execute(
            "SELECT COUNT(*), SUM(status='reduced'), SUM(status='ended'), SUM(status='failed')"
            " FROM sessions"
        ).fetchone()
        if sess_row and sess_row[0]:
            total, reduced, ended, failed = sess_row
            table.add_row(
                "Sessions",
                f"{total} total ({reduced or 0} reduced, {ended or 0} ended, "
                f"{failed or 0} failed)",
            )
        else:
            table.add_row("Sessions", "(none)")
        active = fts.list_files(conn, include_dormant=False)
        dormant = [
            f for f in fts.list_files(conn, include_dormant=True) if f.status == "dormant"
        ]
        total_entries = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        table.add_row(
            "Memory",
            f"{len(active)} active files, {len(dormant)} dormant, {total_entries} entries",
        )
        tlb_row = conn.execute(
            "SELECT COUNT(*), MAX(end_time) FROM timeline_blocks"
        ).fetchone()
        tlb_count = tlb_row[0] if tlb_row else 0
        tlb_last = tlb_row[1] if tlb_row and tlb_row[1] else "(none)"
        table.add_row("Timeline", f"{tlb_count} blocks, last end: {tlb_last}")

    stages = ("timeline", "reducer", "classifier", "compact")
    ping_results = _ping_stages(cfg, stages)
    for stage in stages:
        m = cfg.model_for(stage)
        ping = _format_ping(ping_results.get(stage))
        table.add_row(f"Model ({stage})", f"{m.model}   {ping}")

    console.print(table)


def _ping_stages(cfg: config_mod.Config, stages: tuple[str, ...]) -> dict:
    """Probe each stage's configured model, deduping identical configs.

    Returns a dict keyed by stage name -> PingResult. Pings run in parallel
    so a single hung provider can't stretch the wait past the per-call
    timeout.
    """
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import replace

    from .writer.llm import PingResult, ping_stage

    # Dedup by (model, base_url, resolved api key) — common case is one model
    # for all four stages, which should hit the network once.
    dedup: dict[tuple[str, str, str], list[str]] = {}
    for stage in stages:
        m = cfg.model_for(stage)
        key = (m.model, m.base_url, config_mod.resolve_api_key(m) or "")
        dedup.setdefault(key, []).append(stage)

    results: dict = {}
    if not dedup:
        return results
    with ThreadPoolExecutor(max_workers=min(4, len(dedup))) as pool:
        future_to_stages = {
            pool.submit(ping_stage, cfg, members[0]): members
            for members in dedup.values()
        }
        for future, members in future_to_stages.items():
            try:
                res = future.result(timeout=12.0)
            except Exception as exc:  # noqa: BLE001
                err_label = type(exc).__name__
                for stage in members:
                    m = cfg.model_for(stage)
                    results[stage] = PingResult(
                        stage=stage, model=m.model, ok=False,
                        latency_ms=None, error=err_label,
                    )
                continue
            for stage in members:
                # Reuse the same PingResult across stages that share a config,
                # but tag each with its own stage name so callers can map back.
                results[stage] = replace(res, stage=stage)
    return results


def _format_ping(res) -> str:
    """Render a PingResult as a short Rich-styled cell."""
    if res is None:
        return "[dim]?[/dim]"
    if res.mocked:
        return "[dim]✓ mocked[/dim]"
    if res.ok:
        latency = f"{res.latency_ms} ms" if res.latency_ms is not None else "ok"
        return f"[green]✓[/green] {latency}"
    err = res.error or "failed"
    return f"[red]✗[/red] {err}"


@app.command()
def mcp() -> None:
    """Run the MCP server (stdio). For LLM client config."""
    _init()
    from .mcp import server as mcp_server

    mcp_server.run_stdio()


install_app = typer.Typer(help="Register the MCP server with common LLM clients.")
app.add_typer(install_app, name="install")

uninstall_app = typer.Typer(help="Remove OpenChronicle's MCP entry from LLM clients.")
app.add_typer(uninstall_app, name="uninstall")


@install_app.command("claude-code")
def install_claude_code(
    name: str = typer.Option("openchronicle", help="MCP server name shown to the client."),
    scope: str = typer.Option("user", help="Claude Code scope: user | local | project."),
) -> None:
    """Add (or refresh) OpenChronicle's entry in Claude Code's MCP config.

    Always installs the current URL/transport — if an entry named ``name`` already
    exists at the given scope, it is removed and re-registered.
    """
    cfg = _init()
    from .mcp import server as mcp_server

    if cfg.mcp.transport not in ("sse", "streamable-http"):
        console.print(
            f"[red]MCP transport is {cfg.mcp.transport!r}; install requires sse or streamable-http.[/red]"
        )
        raise typer.Exit(1)
    if not cfg.mcp.auto_start:
        console.print(
            "[yellow]Warning: mcp.auto_start is false — the daemon won't host the server.[/yellow]"
        )

    claude_bin = shutil.which("claude")
    if not claude_bin:
        console.print(
            "[red]`claude` CLI not found on PATH.[/red] "
            "Install Claude Code first, or edit ~/.claude.json manually."
        )
        raise typer.Exit(1)

    url = mcp_server.endpoint_url(cfg)
    transport_flag = "sse" if cfg.mcp.transport == "sse" else "http"

    remove = subprocess.run(
        [claude_bin, "mcp", "remove", "-s", scope, name],
        capture_output=True, text=True, check=False,
    )
    replaced = remove.returncode == 0

    cmd = [
        claude_bin, "mcp", "add",
        "-s", scope,
        "--transport", transport_flag,
        name, url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        console.print(f"[red]claude mcp add failed:[/red]\n{result.stderr or result.stdout}")
        raise typer.Exit(result.returncode)

    verb = "Updated" if replaced else "Registered"
    console.print(f"[green]{verb} {name!r} in Claude Code ({scope} scope).[/green]")
    console.print(f"  URL: {url}")
    console.print(
        "  Make sure the daemon is running (`openchronicle start`) so the server is reachable."
    )


def _claude_desktop_config_path() -> Path:
    return (
        Path.home()
        / "Library"
        / "Application Support"
        / "Claude"
        / "claude_desktop_config.json"
    )


def _load_claude_desktop_config(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        console.print(
            f"[red]Could not parse {path}:[/red] {exc}\n"
            "Fix the JSON or move the file aside and rerun."
        )
        raise typer.Exit(1) from exc
    if not isinstance(data, dict):
        console.print(f"[red]Unexpected top-level shape in {path} (expected object).[/red]")
        raise typer.Exit(1)
    return data


def _restart_reminder(action: str) -> None:
    console.print(
        f"[yellow]Claude Desktop must be fully quit (Cmd+Q) and reopened to {action}.[/yellow]"
    )
    console.print(
        "[dim]The app only reads claude_desktop_config.json at launch. You won't need to "
        "re-login — restart is enough, your session persists.[/dim]"
    )


@install_app.command("claude-desktop")
def install_claude_desktop(
    name: str = typer.Option("openchronicle", help="MCP server name shown to the client."),
) -> None:
    """Add (or refresh) OpenChronicle's entry in Claude Desktop's MCP config.

    Claude Desktop's JSON config only accepts stdio servers (remote SSE/HTTP
    must be added via Settings → Integrations UI), so we register
    ``openchronicle mcp`` as a subprocess command.

    Every invocation is idempotent — existing entries with the same name are
    overwritten with the current absolute path.
    """
    openchronicle_bin = shutil.which("openchronicle")
    if not openchronicle_bin:
        console.print(
            "[red]`openchronicle` not found on PATH.[/red]\n"
            "Install it globally first with [cyan]uv tool install .[/cyan] "
            "(from the repo), then rerun this command."
        )
        raise typer.Exit(1)

    cfg_path = _claude_desktop_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)

    data = _load_claude_desktop_config(cfg_path)
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        console.print(f"[red]`mcpServers` in {cfg_path} is not an object.[/red]")
        raise typer.Exit(1)

    replaced = name in servers
    servers[name] = {
        "command": openchronicle_bin,
        "args": ["mcp"],
    }

    cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    verb = "Updated" if replaced else "Registered"
    console.print(f"[green]{verb} {name!r} in Claude Desktop config.[/green]")
    console.print(f"  file: {cfg_path}")
    console.print(f"  command: {openchronicle_bin} mcp")
    _restart_reminder("pick up the new entry")


@install_app.command("codex")
def install_codex(
    name: str = typer.Option("openchronicle", help="MCP server name shown to the client."),
) -> None:
    """Add (or refresh) OpenChronicle's entry in Codex CLI's MCP config.

    Codex CLI supports streamable-HTTP MCP servers via ``codex mcp add <name> --url <URL>``,
    so we register the daemon's always-on endpoint. The CLI and the IDE extension
    share this config, so a single install covers both clients.

    Every invocation is idempotent — if an entry named ``name`` already exists,
    it is removed and re-registered with the current URL.
    """
    cfg = _init()
    from .mcp import server as mcp_server

    if cfg.mcp.transport not in ("sse", "streamable-http"):
        console.print(
            f"[red]MCP transport is {cfg.mcp.transport!r}; install requires sse or streamable-http.[/red]"
        )
        raise typer.Exit(1)
    if not cfg.mcp.auto_start:
        console.print(
            "[yellow]Warning: mcp.auto_start is false — the daemon won't host the server.[/yellow]"
        )

    codex_bin = shutil.which("codex")
    if not codex_bin:
        console.print(
            "[red]`codex` CLI not found on PATH.[/red] "
            "Install Codex first (https://github.com/openai/codex), "
            "or edit ~/.codex/config.toml manually."
        )
        raise typer.Exit(1)

    url = mcp_server.endpoint_url(cfg)

    remove = subprocess.run(
        [codex_bin, "mcp", "remove", name],
        capture_output=True, text=True, check=False,
    )
    replaced = remove.returncode == 0

    cmd = [codex_bin, "mcp", "add", name, "--url", url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        console.print(f"[red]codex mcp add failed:[/red]\n{result.stderr or result.stdout}")
        raise typer.Exit(result.returncode)

    verb = "Updated" if replaced else "Registered"
    console.print(f"[green]{verb} {name!r} in Codex CLI.[/green]")
    console.print(f"  URL: {url}")
    console.print(
        "  Make sure the daemon is running (`openchronicle start`) so the server is reachable."
    )


def _opencode_config_path() -> Path:
    return Path.home() / ".config" / "opencode" / "opencode.json"


def _load_opencode_config(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        console.print(
            f"[red]Could not parse {path}:[/red] {exc}\n"
            "If your config is JSONC (with comments), edit the `mcp` section manually."
        )
        raise typer.Exit(1) from exc
    if not isinstance(data, dict):
        console.print(f"[red]Unexpected top-level shape in {path} (expected object).[/red]")
        raise typer.Exit(1)
    return data


@install_app.command("opencode")
def install_opencode(
    name: str = typer.Option("openchronicle", help="MCP server name shown to the client."),
) -> None:
    """Add (or refresh) OpenChronicle's entry in opencode's MCP config.

    opencode (https://opencode.ai) reads ``~/.config/opencode/opencode.json``
    and supports remote streamable-HTTP MCP servers natively, so we register
    the daemon's always-on endpoint.

    Every invocation is idempotent — an existing entry named ``name`` is
    overwritten with the current URL; other `mcp` entries are preserved.
    """
    cfg = _init()
    from .mcp import server as mcp_server

    if cfg.mcp.transport not in ("sse", "streamable-http"):
        console.print(
            f"[red]MCP transport is {cfg.mcp.transport!r}; install requires sse or streamable-http.[/red]"
        )
        raise typer.Exit(1)
    if not cfg.mcp.auto_start:
        console.print(
            "[yellow]Warning: mcp.auto_start is false — the daemon won't host the server.[/yellow]"
        )

    cfg_path = _opencode_config_path()
    jsonc_path = cfg_path.with_suffix(".jsonc")
    if jsonc_path.exists():
        url = mcp_server.endpoint_url(cfg)
        console.print(
            f"[red]Found {jsonc_path} — can't safely edit JSONC (comments would be lost).[/red]\n"
            "Add this entry under the `mcp` key manually:\n"
            f'  "{name}": {{"type": "remote", "url": "{url}", "enabled": true}}'
        )
        raise typer.Exit(1)

    existed = cfg_path.exists()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    data = _load_opencode_config(cfg_path)
    if not existed:
        data["$schema"] = "https://opencode.ai/config.json"

    servers = data.setdefault("mcp", {})
    if not isinstance(servers, dict):
        console.print(f"[red]`mcp` in {cfg_path} is not an object.[/red]")
        raise typer.Exit(1)

    url = mcp_server.endpoint_url(cfg)
    replaced = name in servers
    servers[name] = {
        "type": "remote",
        "url": url,
        "enabled": True,
    }

    cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    verb = "Updated" if replaced else "Registered"
    console.print(f"[green]{verb} {name!r} in opencode config.[/green]")
    console.print(f"  URL: {url}")
    console.print(
        "  Make sure the daemon is running (`openchronicle start`) so the server is reachable."
    )


@install_app.command("mcp-json")
def install_mcp_json(
    name: str = typer.Option("openchronicle", help="MCP server name written into the config."),
    filename: str = typer.Option("mcp.json", help="Output filename (written to CWD)."),
    http: bool = typer.Option(
        False, "--http",
        help="Emit a URL-based entry using the configured HTTP endpoint instead of stdio.",
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite if the file exists."),
) -> None:
    """Generate a generic MCP config in the current directory.

    Shape matches the ``mcpServers`` object used by most local agent
    frameworks (Cursor, Cline, Continue, Zed, Windsurf, custom tools). Drop
    the emitted file next to your agent's config or merge its contents into
    an existing one.
    """
    cfg = _init()
    out_path = Path.cwd() / filename
    if out_path.exists() and not force:
        console.print(
            f"[red]{out_path} already exists.[/red] Use --force to overwrite."
        )
        raise typer.Exit(1)

    if http:
        from .mcp import server as mcp_server

        if cfg.mcp.transport not in ("sse", "streamable-http"):
            console.print(
                f"[red]--http requires mcp.transport to be sse or streamable-http, "
                f"got {cfg.mcp.transport!r}.[/red]"
            )
            raise typer.Exit(1)
        url = mcp_server.endpoint_url(cfg)
        transport_label = "sse" if cfg.mcp.transport == "sse" else "http"
        entry: dict[str, object] = {"url": url, "transport": transport_label}
        summary = f"{transport_label} → {url}"
    else:
        openchronicle_bin = shutil.which("openchronicle") or "openchronicle"
        entry = {"command": openchronicle_bin, "args": ["mcp"]}
        summary = f"stdio → {openchronicle_bin} mcp"

    payload = {"mcpServers": {name: entry}}
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    console.print(f"[green]Wrote {out_path}[/green]")
    console.print(f"  server: {name} ({summary})")
    console.print(
        "[dim]Point your agent framework at this file, or merge `mcpServers` "
        "into its existing MCP config.[/dim]"
    )


@uninstall_app.command("claude-code")
def uninstall_claude_code(
    name: str = typer.Option("openchronicle", help="MCP server name to remove."),
    scope: str = typer.Option("user", help="Claude Code scope the entry was installed at."),
) -> None:
    """Remove OpenChronicle's entry from Claude Code's MCP config.

    Scope must match whatever ``install claude-code`` used (default ``user``).
    Missing entries are treated as success — the command is idempotent.
    """
    claude_bin = shutil.which("claude")
    if not claude_bin:
        console.print(
            "[red]`claude` CLI not found on PATH.[/red] "
            "Install Claude Code first, or edit ~/.claude.json manually."
        )
        raise typer.Exit(1)

    result = subprocess.run(
        [claude_bin, "mcp", "remove", "-s", scope, name],
        capture_output=True, text=True, check=False,
    )
    if result.returncode == 0:
        console.print(f"[green]Removed {name!r} from Claude Code ({scope} scope).[/green]")
        return

    combined = (result.stderr + result.stdout).lower()
    if "no mcp server" in combined or "not found" in combined:
        console.print(
            f"[yellow]No {name!r} entry at {scope} scope — nothing to remove.[/yellow]"
        )
        return

    console.print(f"[red]claude mcp remove failed:[/red]\n{result.stderr or result.stdout}")
    raise typer.Exit(result.returncode)


@uninstall_app.command("codex")
def uninstall_codex(
    name: str = typer.Option("openchronicle", help="MCP server name to remove."),
) -> None:
    """Remove OpenChronicle's entry from Codex CLI's MCP config.

    Missing entries are treated as success — the command is idempotent.
    """
    codex_bin = shutil.which("codex")
    if not codex_bin:
        console.print(
            "[red]`codex` CLI not found on PATH.[/red] "
            "Install Codex first, or edit ~/.codex/config.toml manually."
        )
        raise typer.Exit(1)

    result = subprocess.run(
        [codex_bin, "mcp", "remove", name],
        capture_output=True, text=True, check=False,
    )
    if result.returncode == 0:
        console.print(f"[green]Removed {name!r} from Codex CLI.[/green]")
        return

    combined = (result.stderr + result.stdout).lower()
    if "no mcp server" in combined or "not found" in combined or "does not exist" in combined:
        console.print(f"[yellow]No {name!r} entry in Codex config — nothing to remove.[/yellow]")
        return

    console.print(f"[red]codex mcp remove failed:[/red]\n{result.stderr or result.stdout}")
    raise typer.Exit(result.returncode)


@uninstall_app.command("opencode")
def uninstall_opencode(
    name: str = typer.Option("openchronicle", help="MCP server name to remove."),
) -> None:
    """Remove OpenChronicle's entry from opencode's MCP config.

    Missing config / missing entry are treated as success — the command is
    idempotent.
    """
    cfg_path = _opencode_config_path()
    if not cfg_path.exists():
        console.print(
            f"[yellow]No opencode config at {cfg_path} — nothing to remove.[/yellow]"
        )
        return

    data = _load_opencode_config(cfg_path)
    servers = data.get("mcp")
    if not isinstance(servers, dict) or name not in servers:
        console.print(
            f"[yellow]No {name!r} entry in opencode config — nothing to remove.[/yellow]"
        )
        return

    del servers[name]
    cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    console.print(f"[green]Removed {name!r} from opencode config.[/green]")


@uninstall_app.command("claude-desktop")
def uninstall_claude_desktop(
    name: str = typer.Option("openchronicle", help="MCP server name to remove."),
) -> None:
    """Remove OpenChronicle's entry from Claude Desktop's MCP config.

    Missing config / missing entry are treated as success — the command is
    idempotent.
    """
    cfg_path = _claude_desktop_config_path()
    if not cfg_path.exists():
        console.print(
            f"[yellow]No Claude Desktop config at {cfg_path} — nothing to remove.[/yellow]"
        )
        return

    data = _load_claude_desktop_config(cfg_path)
    servers = data.get("mcpServers")
    if not isinstance(servers, dict) or name not in servers:
        console.print(f"[yellow]No {name!r} entry in Claude Desktop config — nothing to remove.[/yellow]")
        return

    del servers[name]
    cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    console.print(f"[green]Removed {name!r} from Claude Desktop config.[/green]")
    _restart_reminder("finalize the removal")


timeline_app = typer.Typer(help="Timeline (short-window activity blocks) subcommands.")
app.add_typer(timeline_app, name="timeline")


@timeline_app.command("tick")
def timeline_tick_cmd() -> None:
    """Build any closed timeline windows right now (synchronous)."""
    cfg = _init()
    from .timeline import tick as tick_mod

    produced = tick_mod.tick_now(cfg)
    console.print(f"[green]Produced {produced} block(s).[/green]")


@timeline_app.command("list")
def timeline_list(
    limit: int = typer.Option(12, "--limit", "-n", help="How many recent blocks to show."),
) -> None:
    """Show the most recent timeline blocks (oldest → newest)."""
    _init()
    from .timeline import store as tls

    with fts.cursor() as conn:
        blocks = tls.query_recent(conn, limit=limit)
    if not blocks:
        console.print("[yellow]No timeline blocks yet.[/yellow]")
        return
    for b in blocks:
        apps = ", ".join(b.apps_used) or "—"
        console.print(
            f"[bold]{b.start_time.strftime('%Y-%m-%d %H:%M')}"
            f"–{b.end_time.strftime('%H:%M')}[/bold] "
            f"({b.capture_count} captures, apps: {apps})"
        )
        for e in b.entries:
            console.print(f"  - {e}")


writer_app = typer.Typer(help="Writer subcommands.")
app.add_typer(writer_app, name="writer")


@writer_app.command("run")
def writer_run() -> None:
    """Reduce any pending sessions and run the classifier on each result."""
    cfg = _init()
    from .writer import agent

    result = agent.run(cfg)
    console.print(
        f"[bold]reduced={result.reduced} "
        f"classified={result.classified} "
        f"written={len(result.written_ids)}[/bold]"
    )
    for s in result.summaries:
        console.print(f"  - {s}")


@app.command("capture-once")
def capture_once() -> None:
    """Perform one capture immediately (useful for testing)."""
    cfg = _init()
    from .capture import ax_capture, scheduler

    provider = ax_capture.create_provider(
        depth=cfg.capture.ax_depth, timeout=cfg.capture.ax_timeout_seconds
    )
    path = scheduler.capture_once(cfg.capture, provider)
    if path:
        console.print(f"[green]Wrote {path}[/green]")
    else:
        console.print("[red]Capture skipped or failed (check logs).[/red]")
        raise typer.Exit(1)


@app.command("rebuild-index")
def rebuild_index() -> None:
    """Rebuild SQLite FTS index from Markdown files on disk."""
    _init()
    with fts.cursor() as conn:
        files_count, entry_count = entries_mod.rebuild_index(conn)
        index_md.rebuild(conn)
    console.print(
        f"[green]Rebuilt: {files_count} files, {entry_count} entries.[/green]"
    )


@app.command("rebuild-captures-index")
def rebuild_captures_index() -> None:
    """Backfill captures_fts from capture-buffer/*.json on disk.

    Re-runnable: existing rows are upserted via INSERT OR REPLACE, so this
    is safe to invoke any time the captures index has fallen out of sync
    (e.g. fresh upgrade onto a populated buffer, or an FTS write the
    capture worker logged but didn't commit).
    """
    import json

    _init()
    buf = paths.capture_buffer_dir()
    if not buf.exists():
        console.print("[yellow]No capture-buffer directory; nothing to rebuild.[/yellow]")
        return

    files = sorted(p for p in buf.iterdir() if p.is_file() and p.suffix == ".json")
    if not files:
        console.print("[yellow]capture-buffer is empty; nothing to rebuild.[/yellow]")
        return

    indexed = 0
    skipped = 0
    with fts.cursor() as conn:
        for p in files:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                skipped += 1
                console.print(f"[yellow]skip {p.name}: {exc}[/yellow]")
                continue
            meta = data.get("window_meta") or {}
            focused = data.get("focused_element") or {}
            try:
                fts.insert_capture(
                    conn,
                    id=p.stem,
                    timestamp=data.get("timestamp", ""),
                    app_name=meta.get("app_name") or "",
                    bundle_id=meta.get("bundle_id") or "",
                    window_title=meta.get("title") or "",
                    focused_role=focused.get("role") or "",
                    focused_value=focused.get("value") or "",
                    visible_text=data.get("visible_text") or "",
                    url=data.get("url") or "",
                )
                indexed += 1
            except Exception as exc:  # noqa: BLE001
                skipped += 1
                console.print(f"[yellow]skip {p.name}: {exc}[/yellow]")
            if indexed % 200 == 0 and indexed > 0:
                console.print(f"  indexed {indexed} / {len(files)}…")

    console.print(
        f"[green]Captures index rebuilt: {indexed} indexed, {skipped} skipped "
        f"(of {len(files)} files).[/green]"
    )


@app.command()
def config() -> None:
    """Print the resolved config path and contents."""
    _init()
    p = paths.config_file()
    console.print(f"[bold]{p}[/bold]")
    console.print(p.read_text(encoding="utf-8"))


clean_app = typer.Typer(help="Delete past data. Destructive — use with care.")
app.add_typer(clean_app, name="clean")


def _confirm(prompt: str, yes: bool) -> bool:
    if yes:
        return True
    return typer.confirm(prompt, default=False)


def _warn_if_running() -> None:
    pid = _read_pid()
    if pid:
        console.print(
            f"[yellow]Warning: daemon is running (pid {pid}). "
            "Consider `openchronicle stop` first — new data may arrive mid-clean.[/yellow]"
        )


def _clean_captures() -> int:
    buf = paths.capture_buffer_dir()
    if not buf.exists():
        return 0
    n = 0
    for p in buf.iterdir():
        if p.suffix == ".json" and p.is_file():
            p.unlink()
            n += 1
    return n


def _clean_timeline() -> int:
    with fts.cursor() as conn:
        n = conn.execute("SELECT COUNT(*) FROM timeline_blocks").fetchone()[0]
        conn.execute("DELETE FROM timeline_blocks")
    return n


def _clean_memory() -> tuple[int, int]:
    """Delete memory Markdown files + reset entries/files tables. Returns (files, entries)."""
    mem = paths.memory_dir()
    files = 0
    if mem.exists():
        for p in mem.rglob("*.md"):
            if p.is_file():
                p.unlink()
                files += 1
    with fts.cursor() as conn:
        entries = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        conn.execute("DELETE FROM entries")
        conn.execute("DELETE FROM files")
    return files, entries


def _clean_writer_state() -> bool:
    p = paths.writer_state()
    if p.exists():
        p.unlink()
        return True
    return False


@clean_app.command("captures")
def clean_captures(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete all files in the capture buffer."""
    _init()
    buf = paths.capture_buffer_dir()
    count = sum(1 for p in buf.iterdir() if p.suffix == ".json") if buf.exists() else 0
    console.print(f"About to delete {count} capture file(s) under {buf}")
    _warn_if_running()
    if not _confirm("Proceed?", yes):
        console.print("[yellow]Aborted.[/yellow]")
        raise typer.Exit(1)
    n = _clean_captures()
    console.print(f"[green]Deleted {n} capture file(s).[/green]")


@clean_app.command("timeline")
def clean_timeline(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete all timeline blocks (short-window activity summaries)."""
    _init()
    with fts.cursor() as conn:
        count = conn.execute("SELECT COUNT(*) FROM timeline_blocks").fetchone()[0]
    console.print(f"About to delete {count} timeline block(s).")
    if not _confirm("Proceed?", yes):
        console.print("[yellow]Aborted.[/yellow]")
        raise typer.Exit(1)
    n = _clean_timeline()
    console.print(f"[green]Deleted {n} timeline block(s).[/green]")


@clean_app.command("memory")
def clean_memory(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete all memory Markdown files and reset the FTS index."""
    _init()
    mem = paths.memory_dir()
    md_count = sum(1 for _ in mem.rglob("*.md")) if mem.exists() else 0
    with fts.cursor() as conn:
        entry_count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        file_count = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    console.print(
        f"About to delete {md_count} Markdown file(s) under {mem} "
        f"and reset {entry_count} entries / {file_count} files in the index."
    )
    _warn_if_running()
    if not _confirm("Proceed?", yes):
        console.print("[yellow]Aborted.[/yellow]")
        raise typer.Exit(1)
    files, entries = _clean_memory()
    console.print(
        f"[green]Deleted {files} Markdown file(s); cleared {entries} index entries.[/green]"
    )


@clean_app.command("all")
def clean_all(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete captures, timeline blocks, memory, and writer state. Config is kept."""
    _init()
    buf = paths.capture_buffer_dir()
    mem = paths.memory_dir()
    capture_count = sum(1 for p in buf.iterdir() if p.suffix == ".json") if buf.exists() else 0
    md_count = sum(1 for _ in mem.rglob("*.md")) if mem.exists() else 0
    with fts.cursor() as conn:
        entry_count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        tlb_count = conn.execute("SELECT COUNT(*) FROM timeline_blocks").fetchone()[0]

    console.print(
        "[bold red]This will delete:[/bold red]\n"
        f"  - {capture_count} capture file(s)\n"
        f"  - {tlb_count} timeline block(s)\n"
        f"  - {md_count} memory Markdown file(s) and {entry_count} index entries\n"
        f"  - writer state\n"
        "[bold]Config ({}) is kept.[/bold]".format(paths.config_file())
    )
    _warn_if_running()
    if not _confirm("Proceed with full wipe?", yes):
        console.print("[yellow]Aborted.[/yellow]")
        raise typer.Exit(1)

    c = _clean_captures()
    t = _clean_timeline()
    f, e = _clean_memory()
    s = _clean_writer_state()
    console.print(
        f"[green]Done. Removed {c} captures, {t} timeline blocks, "
        f"{f} memory files, {e} index entries, writer_state={s}.[/green]"
    )


if __name__ == "__main__":
    app()
