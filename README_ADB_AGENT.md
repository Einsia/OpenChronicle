# OpenChronicle ADB Agent

This document explains the minimal Android ADB control layer added on top of
OpenChronicle.

Architecture:

```text
Codex / Claude Code / Hermes Agent
  -> MCP tool call
  -> OpenChronicle ADB Control MCP Server
  -> adb
  -> Android device
  -> OpenChronicle event memory
```

The original OpenChronicle memory MCP server is unchanged. The ADB server is a
separate stdio MCP server started with:

```powershell
uv run openchronicle adb-mcp
```

## Tools

The ADB MCP server exposes these tools:

- `adb_list_devices`
- `adb_screenshot`
- `adb_dump_ui`
- `adb_tap`
- `adb_swipe`
- `adb_input_text`
- `adb_keyevent`
- `adb_current_app`
- `adb_open_app`
- `adb_read_logcat`

Every tool call appends an entry to OpenChronicle's daily
`event-YYYY-MM-DD.md` memory file. Screenshots are written under:

```text
<OPENCHRONICLE_ROOT>/adb/screenshots/
```

## Safety Policy

The ADB command runner denies high-risk operations before subprocess execution.

Blocked by default:

- `adb uninstall`
- `adb reboot`
- `adb root`, `adb unroot`, `adb remount`
- `adb disable-verity`, `adb enable-verity`
- `adb shell rm`, `adb shell rmdir`
- `adb shell pm clear`
- `adb shell pm uninstall`
- `adb shell cmd package clear`
- `adb shell cmd package uninstall`
- `adb shell settings put/delete/reset`
- `adb shell content delete`
- `adb shell su`
- `adb shell input keyevent POWER`
- `adb shell input keyevent 26`

`adb_input_text` rejects shell metacharacters and records only text length in
memory, not the raw text.

Agent operating rules:

1. Call `adb_screenshot` or `adb_dump_ui` before `adb_tap`, `adb_swipe`, or
   `adb_input_text`.
2. Stop and ask the user before payments, login passwords, SMS codes, privacy
   grants, account changes, or destructive workflows.
3. Do not ask for a generic adb shell. Use the fixed tools only.

## Connect a Phone

1. On the Android phone, enable Developer options.
2. Enable USB debugging.
3. Connect the phone by USB.
4. Accept the RSA debugging prompt on the phone.
5. Verify from PowerShell:

```powershell
E:\ai\product\.tooling\platform-tools\adb.exe devices -l
```

Expected output:

```text
List of devices attached
<serial> device ...
```

If the device is `unauthorized`, unlock the phone and accept the USB debugging
prompt. If it is `offline`, unplug/replug USB or restart the adb server.

## ADB Path Resolution

The server looks for adb in this order:

1. `OPENCHRONICLE_ADB_PATH`
2. `ADB_PATH`
3. `ANDROID_HOME/platform-tools`
4. `ANDROID_SDK_ROOT/platform-tools`
5. `PATH`
6. local `.tooling/platform-tools` or `.tool/platform-tools` directories in the
   current working directory or one of its parents

Windows 11 example:

```powershell
$env:OPENCHRONICLE_ADB_PATH = "E:\ai\product\.tooling\platform-tools\adb.exe"
uv run openchronicle adb-mcp
```

WSL2 example using the Windows adb.exe:

```bash
export OPENCHRONICLE_ADB_PATH=/mnt/e/ai/product/.tooling/platform-tools/adb.exe
uv run openchronicle adb-mcp
```

Native Linux adb inside WSL2 can also work, but USB needs to be attached to WSL
with `usbipd-win`; using Windows `adb.exe` is simpler for this MVP.

## Codex / Claude / Hermes MCP Config

Generic stdio MCP config:

```json
{
  "mcpServers": {
    "openchronicle-adb": {
      "command": "uv",
      "args": ["run", "openchronicle", "adb-mcp"]
    }
  }
}
```

Codex CLI can also register a stdio server from the repo:

```powershell
codex mcp add openchronicle-adb -- uv run openchronicle adb-mcp
```

Claude Code can register the same stdio command:

```powershell
claude mcp add openchronicle-adb -- uv run openchronicle adb-mcp
```

Keep the existing OpenChronicle memory MCP configured separately if you also
want memory search tools. Use `openchronicle adb-mcp` only for phone control.

## Quick Self-Test

Run these from the repository root:

```powershell
E:\ai\product\.tooling\platform-tools\adb.exe devices -l
uv run pytest tests/test_adb_control.py
uv run openchronicle adb-mcp
```

MCP client smoke test:

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(
        command="uv",
        args=["run", "openchronicle", "adb-mcp"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print([tool.name for tool in tools.tools])

asyncio.run(main())
```

To call the phone through MCP, use `adb_list_devices` first. That call should
return the visible device list and create an `event-YYYY-MM-DD.md` memory entry.
