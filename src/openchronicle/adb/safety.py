"""Safety policy for Android ADB commands.

The ADB MCP server intentionally exposes only a small set of fixed tools, but
this module is still called by the command runner so future helpers cannot
accidentally bypass the same denylist.
"""

from __future__ import annotations

import shlex
from collections.abc import Sequence


class ADBSafetyError(ValueError):
    """Raised when an ADB command violates the local safety policy."""


_BLOCKED_TOP_LEVEL = {
    "disable-verity",
    "enable-verity",
    "reboot",
    "remount",
    "root",
    "sideload",
    "uninstall",
    "unroot",
}

_BLOCKED_SHELL_COMMANDS = {
    "reboot",
    "rm",
    "rmdir",
    "su",
    "wipe",
}

_BLOCKED_SEQUENCES = (
    ("cmd", "package", "clear"),
    ("cmd", "package", "uninstall"),
    ("content", "delete"),
    ("pm", "clear"),
    ("pm", "uninstall"),
    ("settings", "delete"),
    ("settings", "put"),
    ("settings", "reset"),
)

_BLOCKED_KEYEVENTS = {
    "26",  # KEYCODE_POWER
    "223",  # KEYCODE_SLEEP
    "224",  # KEYCODE_WAKEUP
    "keycode_power",
    "keycode_sleep",
    "keycode_wakeup",
    "power",
    "sleep",
    "wakeup",
}


def _split_token(token: str) -> list[str]:
    try:
        return shlex.split(token)
    except ValueError:
        return [token]


def _flatten(args: Sequence[str]) -> list[str]:
    out: list[str] = []
    for arg in args:
        text = str(arg).strip()
        if not text:
            continue
        out.extend(_split_token(text))
    return [part.lower() for part in out if part]


def _contains_sequence(tokens: Sequence[str], sequence: Sequence[str]) -> bool:
    if not sequence or len(sequence) > len(tokens):
        return False
    last_start = len(tokens) - len(sequence)
    return any(tuple(tokens[i : i + len(sequence)]) == tuple(sequence) for i in range(last_start + 1))


def _is_blocked_keyevent(value: str) -> bool:
    token = value.lower()
    raw_key = token.removeprefix("keycode_")
    if token in _BLOCKED_KEYEVENTS or raw_key in _BLOCKED_KEYEVENTS:
        return True
    try:
        numeric_key = str(int(raw_key, 0))
    except ValueError:
        if not raw_key.isdecimal():
            return False
        numeric_key = str(int(raw_key, 10))
    return numeric_key in _BLOCKED_KEYEVENTS


def assert_safe(args: Sequence[str]) -> None:
    """Reject destructive or privilege-escalating ADB commands.

    Blocked categories:
    - device reboot/root/remount/verity changes
    - app uninstall or app data clearing
    - shell deletion commands
    - system settings mutation
    - POWER/SLEEP/WAKEUP keyevents
    """
    tokens = _flatten(args)
    if not tokens:
        raise ADBSafetyError("empty adb command is not allowed")

    for token in tokens:
        if token in _BLOCKED_TOP_LEVEL:
            raise ADBSafetyError(f"blocked high-risk adb command: {token}")

    shell_tokens = tokens
    if "shell" in tokens:
        shell_tokens = tokens[tokens.index("shell") + 1 :]

    for token in shell_tokens:
        if token in _BLOCKED_SHELL_COMMANDS:
            raise ADBSafetyError(f"blocked high-risk adb shell command: {token}")

    for sequence in _BLOCKED_SEQUENCES:
        if _contains_sequence(shell_tokens, sequence):
            raise ADBSafetyError("blocked high-risk adb shell command: " + " ".join(sequence))

    if _contains_sequence(shell_tokens, ("input", "keyevent")):
        idx = shell_tokens.index("keyevent")
        if idx + 1 < len(shell_tokens) and _is_blocked_keyevent(shell_tokens[idx + 1]):
            raise ADBSafetyError(f"blocked high-risk keyevent: {shell_tokens[idx + 1]}")


def validate_input_text(text: str) -> str:
    """Return Android input-text syntax for safe text.

    `adb shell input text` runs through the device shell. Reject shell
    metacharacters instead of trying to quote arbitrary text across host and
    device shells. Spaces are encoded as `%s`, which is Android's input syntax.
    """
    if text == "":
        raise ADBSafetyError("adb_input_text requires non-empty text")
    blocked = set("\r\n;&|<>`$(){}[]\\\"'")
    bad = sorted({ch for ch in text if ch in blocked})
    if bad:
        shown = " ".join(repr(ch) for ch in bad)
        raise ADBSafetyError(f"adb_input_text rejected shell metacharacter(s): {shown}")
    return text.replace(" ", "%s")
