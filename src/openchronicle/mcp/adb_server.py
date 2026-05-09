"""MCP server exposing safe Android ADB control tools."""

from __future__ import annotations

import json

from ..adb import ADBController
from ..config import Config

_SERVER_INSTRUCTIONS = """\
# OpenChronicle ADB Control

This MCP server lets an agent operate an Android device through a small, safe
ADB tool surface. Every tool call is appended to OpenChronicle's daily
event-YYYY-MM-DD.md memory file.

Rules for agents:

1. Observe before acting: call adb_screenshot or adb_dump_ui before tap/swipe/text.
2. Do not request delete, uninstall, clear-data, root, reboot, remount, or settings writes.
3. Stop and ask the user before payments, passwords, SMS codes, private data export, or account changes.
4. Prefer package/activity based app launch over blind navigation when the package is known.
"""


def build_server(cfg: Config | None = None, controller: ADBController | None = None):
    """Construct and return a FastMCP server instance for ADB control."""
    from mcp.server.fastmcp import FastMCP

    del cfg  # The ADB server is stdio-first and currently has no config section.
    adb = controller or ADBController()
    server = FastMCP("openchronicle-adb", instructions=_SERVER_INSTRUCTIONS)

    @server.tool()
    def adb_list_devices() -> str:
        """List Android devices visible to adb and record the operation in memory."""
        return json.dumps(adb.list_devices(), ensure_ascii=False)

    @server.tool()
    def adb_screenshot(device_id: str | None = None) -> str:
        """Capture a PNG screenshot from the Android device and return its local path."""
        return json.dumps(adb.screenshot(device_id=device_id), ensure_ascii=False)

    @server.tool()
    def adb_dump_ui(device_id: str | None = None) -> str:
        """Dump the Android UI Automator XML tree for the current screen."""
        return json.dumps(adb.dump_ui(device_id=device_id), ensure_ascii=False)

    @server.tool()
    def adb_tap(x: int, y: int, device_id: str | None = None) -> str:
        """Tap an Android screen coordinate."""
        return json.dumps(adb.tap(x=x, y=y, device_id=device_id), ensure_ascii=False)

    @server.tool()
    def adb_swipe(
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
        device_id: str | None = None,
    ) -> str:
        """Swipe from one Android screen coordinate to another."""
        return json.dumps(
            adb.swipe(
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2,
                duration_ms=duration_ms,
                device_id=device_id,
            ),
            ensure_ascii=False,
        )

    @server.tool()
    def adb_input_text(text: str, device_id: str | None = None) -> str:
        """Input text through Android's input command. Text is redacted in memory."""
        return json.dumps(adb.input_text(text=text, device_id=device_id), ensure_ascii=False)

    @server.tool()
    def adb_keyevent(keyevent: str, device_id: str | None = None) -> str:
        """Send a safe Android keyevent, such as BACK, HOME, ENTER, or a numeric keycode."""
        return json.dumps(adb.keyevent(keyevent=keyevent, device_id=device_id), ensure_ascii=False)

    @server.tool()
    def adb_current_app(device_id: str | None = None) -> str:
        """Return the foreground Android package/activity when adb can determine it."""
        return json.dumps(adb.current_app(device_id=device_id), ensure_ascii=False)

    @server.tool()
    def adb_open_app(
        package_name: str,
        activity: str | None = None,
        device_id: str | None = None,
    ) -> str:
        """Open an Android app by package name, optionally with an explicit activity."""
        return json.dumps(
            adb.open_app(package_name=package_name, activity=activity, device_id=device_id),
            ensure_ascii=False,
        )

    @server.tool()
    def adb_read_logcat(
        lines: int = 200,
        filter_expr: str | None = None,
        device_id: str | None = None,
    ) -> str:
        """Read bounded logcat output. Defaults to the last 200 lines."""
        return json.dumps(
            adb.read_logcat(lines=lines, filter_expr=filter_expr, device_id=device_id),
            ensure_ascii=False,
        )

    @server.tool()
    def adb_pair(host: str, port: int, code: str, device_id: str | None = None) -> str:
        """Pair adb to a device via wireless debugging (Android 11+)."""
        return json.dumps(
            adb.pair(host=host, port=port, code=code, device_id=device_id),
            ensure_ascii=False,
        )

    @server.tool()
    def adb_connect(host: str, port: int, device_id: str | None = None) -> str:
        """Connect adb to a wireless debugging endpoint."""
        return json.dumps(
            adb.connect(host=host, port=port, device_id=device_id),
            ensure_ascii=False,
        )

    return server


def run_stdio() -> None:
    """Run the ADB MCP server on stdio."""
    build_server().run()


if __name__ == "__main__":
    run_stdio()
