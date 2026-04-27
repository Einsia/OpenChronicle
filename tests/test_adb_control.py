from __future__ import annotations

import pytest

from openchronicle.adb.client import ADBCommandResult
from openchronicle.adb.memory import ADBMemoryRecorder
from openchronicle.adb.safety import ADBSafetyError, assert_safe
from openchronicle.adb.tools import ADBController, _parse_devices
from openchronicle.mcp import adb_server
from openchronicle.store import files as files_mod


class FakeADBClient:
    adb_path = "adb"

    def __init__(self, stdout: str = "", stdout_bytes: bytes = b"") -> None:
        self.stdout = stdout
        self.stdout_bytes = stdout_bytes
        self.calls: list[tuple[list[str], str | None, bool]] = []

    def command_for_display(self, args, device_id=None):
        command = [self.adb_path]
        if device_id:
            command.extend(["-s", device_id])
        command.extend(str(a) for a in args)
        return command

    def run(self, args, *, device_id=None, timeout=30.0, binary=False, check=True):
        del timeout, check
        self.calls.append((list(args), device_id, binary))
        stdout = self.stdout_bytes if binary else self.stdout
        return ADBCommandResult(
            args=self.command_for_display(args, device_id),
            returncode=0,
            stdout=stdout,
            stderr="",
        )


def test_safety_blocks_destructive_commands() -> None:
    blocked = [
        ["uninstall", "com.example.app"],
        ["reboot"],
        ["root"],
        ["shell", "pm", "clear", "com.example.app"],
        ["shell", "settings", "put", "system", "screen_brightness", "1"],
        ["shell", "rm", "-rf", "/sdcard/Download"],
        ["shell", "input", "keyevent", "POWER"],
        ["shell", "input", "keyevent", "26"],
    ]
    for command in blocked:
        with pytest.raises(ADBSafetyError):
            assert_safe(command)


def test_safety_blocks_keyevent_numeric_aliases() -> None:
    blocked = [
        ["shell", "input", "keyevent", "0x1a"],
        ["shell", "input", "keyevent", "0XDF"],
        ["shell", "input", "keyevent", "000224"],
        ["shell", "input", "keyevent", "KEYCODE_WAKEUP"],
    ]
    for command in blocked:
        with pytest.raises(ADBSafetyError):
            assert_safe(command)


def test_safety_allows_mvp_commands() -> None:
    allowed = [
        ["devices", "-l"],
        ["pair", "127.0.0.1:37123", "000000"],
        ["connect", "127.0.0.1:5555"],
        ["exec-out", "screencap", "-p"],
        ["shell", "uiautomator", "dump", "/data/local/tmp/window.xml"],
        ["shell", "input", "tap", "100", "200"],
        ["shell", "input", "swipe", "100", "900", "100", "100", "300"],
        ["shell", "input", "keyevent", "BACK"],
        ["shell", "monkey", "-p", "com.example.app", "-c", "android.intent.category.LAUNCHER", "1"],
    ]
    for command in allowed:
        assert_safe(command)


def test_parse_devices() -> None:
    output = """* daemon not running; starting now at tcp:5037
* daemon started successfully
List of devices attached
emulator-5554 device product:sdk_gphone_x86_64 model:sdk_gphone64 transport_id:1
R58M123 offline usb:1-1
"""
    devices = _parse_devices(output)
    assert devices[0]["serial"] == "emulator-5554"
    assert devices[0]["state"] == "device"
    assert devices[0]["qualifiers"]["product"] == "sdk_gphone_x86_64"
    assert devices[1]["state"] == "offline"


def test_parse_devices_without_header_returns_empty() -> None:
    assert _parse_devices("* daemon started successfully\n") == []


def test_list_devices_writes_openchronicle_event(ac_root) -> None:
    client = FakeADBClient(
        stdout="List of devices attached\nemulator-5554 device product:sdk model:Pixel\n"
    )
    controller = ADBController(client=client, recorder=ADBMemoryRecorder())

    result = controller.list_devices()

    assert result["ok"] is True
    assert result["count"] == 1
    event_files = list((ac_root / "memory").glob("event-*.md"))
    assert len(event_files) == 1
    parsed = files_mod.read_file(event_files[0])
    assert parsed.entries
    assert "ADB tool adb_list_devices" in parsed.entries[-1].body


def test_blocked_input_text_is_recorded(ac_root) -> None:
    controller = ADBController(client=FakeADBClient(), recorder=ADBMemoryRecorder())

    result = controller.input_text("hello; rm -rf /")

    assert result["ok"] is False
    assert result["blocked"] is True
    assert not controller.client.calls
    event_file = next((ac_root / "memory").glob("event-*.md"))
    parsed = files_mod.read_file(event_file)
    assert "blocked by safety policy" in parsed.entries[-1].body


def test_adb_mcp_server_builds() -> None:
    server = adb_server.build_server(controller=ADBController(client=FakeADBClient()))
    assert server is not None


def test_logcat_filter_rejects_flags(ac_root) -> None:
    controller = ADBController(client=FakeADBClient(), recorder=ADBMemoryRecorder())

    result = controller.read_logcat(filter_expr="-c")

    assert result["ok"] is False
    assert result["blocked"] is True
    assert not controller.client.calls


def test_logcat_filter_allows_tag_specs(ac_root) -> None:
    controller = ADBController(client=FakeADBClient(stdout="I/Test: hello"))

    result = controller.read_logcat(filter_expr="Test:D *:S")

    assert result["ok"] is True
    assert controller.client.calls[-1][0] == ["logcat", "-d", "-t", "200", "Test:D", "*:S"]


def test_dump_ui_uses_data_local_tmp() -> None:
    client = FakeADBClient(stdout="UI hierarchy dumped to: /data/local/tmp/window.xml")
    controller = ADBController(client=client)

    controller.dump_ui()

    assert client.calls[0][0] == ["shell", "uiautomator", "dump", "/data/local/tmp/window.xml"]
    assert client.calls[1][0] == ["exec-out", "cat", "/data/local/tmp/window.xml"]


def test_current_app_uses_bounded_dumpsys_window_command() -> None:
    client = FakeADBClient(stdout="mCurrentFocus=Window{u0 com.example/.MainActivity}")
    controller = ADBController(client=client)

    controller.current_app()

    assert client.calls[-1][0] == ["shell", "dumpsys", "window", "windows"]


def test_pair_records_redacted_code(ac_root) -> None:
    client = FakeADBClient(stdout="Successfully paired to 127.0.0.1:37123")
    controller = ADBController(client=client, recorder=ADBMemoryRecorder())

    result = controller.pair(host="127.0.0.1", port=37123, code="000000")

    assert result["ok"] is True
    assert client.calls[-1][0][:2] == ["pair", "127.0.0.1:37123"]
    event_file = next((ac_root / "memory").glob("event-*.md"))
    parsed = files_mod.read_file(event_file)
    assert "<redacted>" in parsed.entries[-1].body


def test_connect_records_address(ac_root) -> None:
    client = FakeADBClient(stdout="connected to 127.0.0.1:5555")
    controller = ADBController(client=client, recorder=ADBMemoryRecorder())

    result = controller.connect(host="127.0.0.1", port=5555)

    assert result["ok"] is True
    assert client.calls[-1][0] == ["connect", "127.0.0.1:5555"]
