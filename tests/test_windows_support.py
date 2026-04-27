from __future__ import annotations

from pathlib import Path

from openchronicle import paths
from openchronicle.capture import s1_parser, windows_uia
from openchronicle.capture.window_meta import WindowMeta


class _Pattern:
    def __init__(self, value: str) -> None:
        self.Value = value


class _Control:
    def __init__(
        self,
        *,
        name: str,
        control_type: str,
        value: str = "",
        children: list[_Control] | None = None,
        focused: bool = False,
        automation_id: str = "",
    ) -> None:
        self.Name = name
        self.ControlTypeName = control_type
        self.Value = value
        self.AutomationId = automation_id
        self.ClassName = ""
        self.ProcessId = 123
        self.HasKeyboardFocus = focused
        self._children = children or []

    def GetChildren(self) -> list[_Control]:
        return self._children

    def GetValuePattern(self) -> _Pattern:
        return _Pattern(self.Value)


class _Auto:
    def __init__(self, foreground: _Control, focused: _Control) -> None:
        self._foreground = foreground
        self._focused = focused

    def GetForegroundControl(self) -> _Control:
        return self._foreground

    def GetFocusedControl(self) -> _Control:
        return self._focused


def test_windows_root_defaults_to_local_app_data(monkeypatch) -> None:
    monkeypatch.delenv("OPENCHRONICLE_ROOT", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\me\AppData\Local")
    monkeypatch.setattr(paths.platform, "system", lambda: "Windows")

    assert paths.root() == Path(r"C:\Users\me\AppData\Local\OpenChronicle")


def test_windows_uia_provider_emits_capture_compatible_tree(monkeypatch) -> None:
    address = _Control(
        name="Address and search bar",
        control_type="EditControl",
        value="https://www.anthropic.com/news",
        focused=True,
        automation_id="address-edit",
    )
    root = _Control(
        name="Anthropic - Google Chrome",
        control_type="WindowControl",
        children=[
            _Control(name="Toolbar", control_type="PaneControl", children=[address]),
            _Control(name="OpenChronicle notes", control_type="TextControl"),
        ],
    )
    monkeypatch.setattr(
        windows_uia,
        "active_window",
        lambda: WindowMeta(app_name="Chrome", title="Anthropic", bundle_id="chrome.exe"),
    )

    provider = windows_uia.WindowsUIAProvider(
        depth=5, timeout=3, auto_module=_Auto(root, address)
    )
    result = provider.capture_frontmost()

    assert result is not None
    assert result.metadata["platform"] == "windows"
    capture = {"ax_tree": result.raw_json}
    s1_parser.enrich(capture)
    assert capture["url"] == "https://www.anthropic.com/news"
    assert capture["focused_element"]["role"] == "AXTextField"


def test_s1_extracts_nested_edge_url() -> None:
    capture = {
        "ax_tree": {
            "apps": [
                {
                    "name": "Edge",
                    "bundle_id": "msedge.exe",
                    "is_frontmost": True,
                    "windows": [
                        {
                            "title": "Example",
                            "focused": True,
                            "elements": [
                                {
                                    "role": "AXGroup",
                                    "children": [
                                        {
                                            "role": "AXTextField",
                                            "title": "Address and search bar",
                                            "value": "example.com/path",
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    }

    s1_parser.enrich(capture)

    assert capture["url"] == "https://example.com/path"


def test_windows_polling_watcher_emits_dispatcher_compatible_events(monkeypatch) -> None:
    metas = iter(
        [
            WindowMeta(app_name="Chrome", title="A", bundle_id="chrome.exe"),
            WindowMeta(app_name="Chrome", title="A", bundle_id="chrome.exe"),
            WindowMeta(app_name="Edge", title="B", bundle_id="msedge.exe"),
        ]
    )
    events = []
    monkeypatch.setattr(windows_uia.platform, "system", lambda: "Windows")
    monkeypatch.setattr(windows_uia, "active_window", lambda: next(metas))

    watcher = windows_uia.WindowsPollingWatcher(interval_seconds=1)
    watcher.on_event(events.append)
    watcher._poll_once()
    watcher._poll_once()
    watcher._poll_once()

    assert [e["event_type"] for e in events] == [
        "AXApplicationActivated",
        "AXValueChanged",
        "AXApplicationActivated",
    ]
