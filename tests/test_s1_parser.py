from __future__ import annotations

from openchronicle.capture import s1_parser


def _ax_tree(*apps: dict) -> dict:
    return {"apps": list(apps), "timestamp": "2026-04-21T10:00:00+08:00"}


def test_enrich_noop_without_ax_tree() -> None:
    capture = {"timestamp": "x", "window_meta": {"app_name": "A"}}
    s1_parser.enrich(capture)
    assert "focused_element" not in capture
    assert "visible_text" not in capture


def test_enrich_picks_frontmost_app() -> None:
    capture = {
        "ax_tree": _ax_tree(
            {"name": "Background", "bundle_id": "b", "is_frontmost": False, "windows": []},
            {
                "name": "Cursor",
                "bundle_id": "com.todesktop.230313mzl4w4u92",
                "is_frontmost": True,
                "focused_element": {
                    "role": "AXTextArea",
                    "title": "editor",
                    "value": "def enrich(capture):\n    ...",
                    "focused": True,
                },
                "windows": [
                    {
                        "title": "s1_parser.py",
                        "focused": True,
                        "elements": [
                            {
                                "role": "AXTextArea",
                                "title": "editor",
                                "value": "def enrich(capture):\n    ...",
                            }
                        ],
                    }
                ],
            },
        )
    }
    s1_parser.enrich(capture)
    assert capture["focused_element"]["role"] == "AXTextArea"
    assert capture["focused_element"]["is_editable"] is True
    assert capture["focused_element"]["has_value"] is True
    assert capture["focused_element"]["value_length"] > 0
    assert "s1_parser.py" in capture["visible_text"]
    assert capture["url"] is None


def test_enrich_extracts_browser_url() -> None:
    capture = {
        "ax_tree": _ax_tree(
            {
                "name": "Chrome",
                "bundle_id": "com.google.Chrome",
                "is_frontmost": True,
                "focused_element": {
                    "role": "AXTextField",
                    "title": "Address and search bar",
                    "value": "https://www.anthropic.com/news",
                    "focused": True,
                },
                "windows": [
                    {
                        "title": "Anthropic",
                        "focused": True,
                        "elements": [
                            {
                                "role": "AXTextField",
                                "title": "Address and search bar",
                                "value": "https://www.anthropic.com/news",
                            }
                        ],
                    }
                ],
            }
        )
    }
    s1_parser.enrich(capture)
    assert capture["url"] == "https://www.anthropic.com/news"
    assert capture["focused_element"]["role"] == "AXTextField"


def test_enrich_prefixes_bare_url() -> None:
    capture = {
        "ax_tree": _ax_tree(
            {
                "name": "Safari",
                "bundle_id": "com.apple.Safari",
                "is_frontmost": True,
                "windows": [
                    {
                        "title": "",
                        "focused": True,
                        "elements": [
                            {
                                "role": "AXTextField",
                                "title": "Address and search bar",
                                "value": "anthropic.com",
                            }
                        ],
                    }
                ],
            }
        )
    }
    s1_parser.enrich(capture)
    assert capture["url"] == "https://anthropic.com"


def test_enrich_recurses_for_explicitly_focused_fallback() -> None:
    capture = {
        "ax_tree": _ax_tree(
            {
                "name": "Chrome",
                "bundle_id": "com.google.Chrome",
                "is_frontmost": True,
                "windows": [
                    {
                        "title": "Nested",
                        "focused": True,
                        "elements": [
                            {
                                "role": "AXGroup",
                                "children": [
                                    {
                                        "role": "AXTextField",
                                        "value": "query",
                                        "focused": True,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        )
    }
    s1_parser.enrich(capture)
    assert capture["focused_element"]["role"] == "AXTextField"
    assert capture["focused_element"]["value"] == "query"


def test_enrich_does_not_guess_first_text_node_as_focus() -> None:
    capture = {
        "ax_tree": _ax_tree(
            {
                "name": "TextEdit",
                "bundle_id": "com.apple.TextEdit",
                "is_frontmost": True,
                "windows": [
                    {
                        "title": "Document",
                        "focused": True,
                        "elements": [
                            {"role": "AXStaticText", "value": "heading"},
                            {"role": "AXTextArea", "value": "body"},
                        ],
                    }
                ],
            }
        )
    }
    s1_parser.enrich(capture)
    assert capture["focused_element"]["role"] == ""


def test_enrich_extracts_nested_combobox_address_bar() -> None:
    capture = {
        "ax_tree": _ax_tree(
            {
                "name": "Chrome",
                "bundle_id": "com.google.Chrome",
                "is_frontmost": True,
                "windows": [
                    {
                        "title": "Example",
                        "focused": True,
                        "elements": [
                            {
                                "role": "AXToolbar",
                                "children": [
                                    {
                                        "role": "AXGroup",
                                        "children": [
                                            {
                                                "role": "AXComboBox",
                                                "identifier": "location_bar",
                                                "value": "HTTPS://Example.COM/Path",
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        )
    }
    s1_parser.enrich(capture)
    assert capture["url"] == "https://example.com/Path"
    assert capture["url_source"] == "ax_address_bar"


def test_enrich_rejects_ambiguous_page_url_fields() -> None:
    capture = {
        "ax_tree": _ax_tree(
            {
                "name": "Chrome",
                "bundle_id": "com.google.Chrome",
                "is_frontmost": True,
                "windows": [
                    {
                        "title": "Form",
                        "focused": True,
                        "elements": [
                            {
                                "role": "AXWebArea",
                                "children": [
                                    {"role": "AXTextField", "value": "https://one.example"},
                                    {"role": "AXTextField", "value": "https://two.example"},
                                ],
                            }
                        ],
                    }
                ],
            }
        )
    }
    s1_parser.enrich(capture)
    assert capture["url"] is None
    assert capture["url_source"] == "unavailable"


def test_normalize_url_handles_supported_special_cases() -> None:
    assert s1_parser._normalize_url(" localhost:8000/path ") == "https://localhost:8000/path"
    assert s1_parser._normalize_url("http://127.0.0.1:8742/MCP") == ("http://127.0.0.1:8742/MCP")
    assert s1_parser._normalize_url("http://[::1]:8080/Path") == ("http://[::1]:8080/Path")
    assert s1_parser._normalize_url("chrome://settings/privacy") == ("chrome://settings/privacy")
    assert s1_parser._normalize_url("file:///Users/example/Test.txt") == (
        "file:///Users/example/Test.txt"
    )
    assert s1_parser._normalize_url("https://user:secret@Example.COM/Path") == (
        "https://example.com/Path"
    )


def test_enrich_does_not_treat_page_search_box_as_address_bar() -> None:
    capture = {
        "ax_tree": _ax_tree(
            {
                "name": "Chrome",
                "bundle_id": "com.google.Chrome",
                "is_frontmost": True,
                "windows": [
                    {
                        "title": "Search form",
                        "focused": True,
                        "elements": [
                            {
                                "role": "AXWebArea",
                                "children": [
                                    {
                                        "role": "AXTextField",
                                        "title": "Search bar",
                                        "value": "https://not-the-page.example",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        )
    }
    s1_parser.enrich(capture)
    assert capture["url"] is None


def test_enrich_non_browser_has_no_url() -> None:
    capture = {
        "ax_tree": _ax_tree(
            {
                "name": "Cursor",
                "bundle_id": "com.todesktop.230313mzl4w4u92",
                "is_frontmost": True,
                "windows": [
                    {
                        "title": "file.py",
                        "focused": True,
                        "elements": [
                            {
                                "role": "AXTextField",
                                "value": "https://example.com",
                            }
                        ],
                    }
                ],
            }
        )
    }
    s1_parser.enrich(capture)
    assert capture["url"] is None


def test_enrich_visible_text_truncation() -> None:
    huge_value = "x" * 20_000
    capture = {
        "ax_tree": _ax_tree(
            {
                "name": "App",
                "bundle_id": "b",
                "is_frontmost": True,
                "windows": [
                    {
                        "title": "T",
                        "focused": True,
                        "elements": [
                            {"role": "AXStaticText", "title": "header", "value": huge_value}
                        ],
                    }
                ],
            }
        )
    }
    s1_parser.enrich(capture)
    assert len(capture["visible_text"]) <= 10_000 + len("\n...(truncated)")
    assert capture["visible_text"].endswith("(truncated)")


def test_enrich_no_focused_window_returns_empty_element() -> None:
    capture = {
        "ax_tree": _ax_tree(
            {
                "name": "App",
                "bundle_id": "b",
                "is_frontmost": True,
                "windows": [
                    {
                        "title": "unfocused",
                        "focused": False,
                        "elements": [{"role": "AXTextField", "value": "something"}],
                    }
                ],
            }
        )
    }
    s1_parser.enrich(capture)
    fe = capture["focused_element"]
    assert fe["role"] == ""
    assert fe["value"] == ""
    assert fe["is_editable"] is False


def test_enrich_empty_ax_tree() -> None:
    capture = {"ax_tree": {"apps": []}}
    s1_parser.enrich(capture)
    assert capture["focused_element"]["role"] == ""
    assert capture["visible_text"] == ""
    assert capture["url"] is None


def test_enrich_falls_back_to_first_app_when_no_frontmost() -> None:
    capture = {
        "ax_tree": _ax_tree(
            {
                "name": "OnlyApp",
                "bundle_id": "b",
                "windows": [
                    {
                        "title": "T",
                        "focused": True,
                        "elements": [{"role": "AXStaticText", "value": "hello"}],
                    }
                ],
            }
        )
    }
    s1_parser.enrich(capture)
    assert "hello" in capture["visible_text"]
