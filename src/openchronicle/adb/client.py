"""Small, safe ADB subprocess wrapper."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import safety


class ADBError(RuntimeError):
    """Raised when an adb subprocess fails."""

    def __init__(
        self,
        message: str,
        *,
        args: Sequence[str] | None = None,
        returncode: int | None = None,
        stdout: str | bytes = "",
        stderr: str = "",
    ) -> None:
        super().__init__(message)
        self.args_list = list(args or [])
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class ADBNotFoundError(ADBError):
    """Raised when no adb executable can be started."""


@dataclass(frozen=True)
class ADBCommandResult:
    args: list[str]
    returncode: int
    stdout: str | bytes
    stderr: str

    @property
    def stdout_text(self) -> str:
        if isinstance(self.stdout, bytes):
            return self.stdout.decode("utf-8", errors="replace")
        return self.stdout

    @property
    def stdout_bytes(self) -> bytes:
        if isinstance(self.stdout, bytes):
            return self.stdout
        return self.stdout.encode("utf-8")


def _tooling_candidates() -> list[Path]:
    names = ("adb.exe", "adb") if platform.system() == "Windows" else ("adb", "adb.exe")
    layouts = (
        (".tooling", "platform-tools"),
        (".tooling", "android-sdk", "platform-tools"),
        (".tool", "platform-tools"),
        (".tool", "android-sdk", "platform-tools"),
    )
    candidates: list[Path] = []
    for parent in (Path.cwd(), *Path.cwd().parents):
        for layout in layouts:
            base = parent.joinpath(*layout)
            for name in names:
                candidates.append(base / name)
    return candidates


def find_adb_path() -> str:
    """Resolve adb from env, PATH, or a local .tooling/.tool platform-tools dir."""
    for env_name in ("OPENCHRONICLE_ADB_PATH", "ADB_PATH"):
        value = os.environ.get(env_name)
        if value:
            return str(Path(value).expanduser())

    for env_name in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        value = os.environ.get(env_name)
        if not value:
            continue
        sdk = Path(value).expanduser()
        for name in ("adb.exe", "adb"):
            candidate = sdk / "platform-tools" / name
            if candidate.exists():
                return str(candidate)

    for name in ("adb.exe", "adb"):
        found = shutil.which(name)
        if found:
            return found

    for candidate in _tooling_candidates():
        if candidate.exists():
            return str(candidate)

    return "adb"


class ADBClient:
    """Run adb commands through a single safety gate."""

    def __init__(self, adb_path: str | None = None) -> None:
        self.adb_path = adb_path or find_adb_path()

    def command_for_display(self, args: Sequence[str], device_id: str | None = None) -> list[str]:
        cmd = [self.adb_path]
        if device_id:
            cmd.extend(["-s", device_id])
        cmd.extend(str(a) for a in args)
        return cmd

    def run(
        self,
        args: Sequence[str],
        *,
        device_id: str | None = None,
        timeout: float = 30.0,
        binary: bool = False,
        check: bool = True,
    ) -> ADBCommandResult:
        safety.assert_safe([str(a) for a in args])
        cmd = self.command_for_display(args, device_id)
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                check=False,
                timeout=timeout,
                text=not binary,
                encoding=None if binary else "utf-8",
                errors=None if binary else "replace",
            )
        except FileNotFoundError as exc:
            raise ADBNotFoundError(
                f"adb executable not found: {self.adb_path!r}. Set OPENCHRONICLE_ADB_PATH.",
                args=cmd,
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ADBError(f"adb command timed out after {timeout:g}s", args=cmd) from exc

        stderr = completed.stderr
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        result = ADBCommandResult(
            args=cmd,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=stderr or "",
        )
        if check and result.returncode != 0:
            message = (result.stderr or result.stdout_text or "adb command failed").strip()
            raise ADBError(
                message,
                args=cmd,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        return result
