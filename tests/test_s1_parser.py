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
                        "elements": [
                            {"role": "AXTextField", "value": "something"}
                        ],
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


# ── Editor / terminal S1 field extraction ────────────────────────────────────


def test_extract_editor_info_standard() -> None:
    """main.py — project-name - Visual Studio Code"""
    file, project, branch = s1_parser._extract_editor_info(
        "main.py — openchronicle - Visual Studio Code",
        "com.microsoft.VSCode",
    )
    assert file == "main.py"
    assert project == "openchronicle"
    assert branch is None


def test_extract_editor_info_with_git_branch() -> None:
    """Cursor with [git:feat/auth] in title."""
    file, project, branch = s1_parser._extract_editor_info(
        "app.ts — website [git:feat/auth] - Cursor",
        "com.todesktop.230313mzl4w4u92",
    )
    assert file == "app.ts"
    assert project == "website"
    assert branch == "git:feat/auth"


def test_extract_editor_info_no_project() -> None:
    """VS Code with no project folder open."""
    file, project, branch = s1_parser._extract_editor_info(
        "main.py - Visual Studio Code",
        "com.microsoft.VSCode",
    )
    assert file == "main.py"
    assert project is None
    assert branch is None


def test_extract_editor_info_wsl_branch() -> None:
    """WSL remote — [WSL:Ubuntu] bracket annotation."""
    file, project, branch = s1_parser._extract_editor_info(
        "config.rs — my-project [WSL:Ubuntu] - Visual Studio Code",
        "com.microsoft.VSCode",
    )
    assert file == "config.rs"
    assert project == "my-project"
    assert branch == "WSL:Ubuntu"


def test_extract_editor_info_bare_bracket_branch() -> None:
    """Bare [main] branch annotation (no git: prefix)."""
    file, project, branch = s1_parser._extract_editor_info(
        "README.md — docs [main] - Visual Studio Code",
        "com.microsoft.VSCode",
    )
    assert file == "README.md"
    assert project == "docs"
    assert branch == "main"


def test_extract_terminal_cwd_iterm2() -> None:
    """iTerm2 default title: command — cwd — shell."""
    cwd = s1_parser._extract_terminal_cwd(
        "vim — ~/projects/foo — zsh"
    )
    assert cwd is not None
    assert cwd.endswith("/projects/foo")


def test_extract_terminal_cwd_ssh() -> None:
    """SSH title: user@host:/path."""
    cwd = s1_parser._extract_terminal_cwd(
        "user@host: /var/www/html"
    )
    assert cwd == "/var/www/html"


def test_extract_terminal_cwd_default() -> None:
    """Default terminal title without a path."""
    cwd = s1_parser._extract_terminal_cwd("Terminal")
    assert cwd is None


def test_extract_terminal_cwd_absolute_path() -> None:
    """Absolute path in terminal title."""
    cwd = s1_parser._extract_terminal_cwd(
        "/tmp/build — bash — 80x24"
    )
    assert cwd == "/tmp/build"


# ── enrich() integration with editor fields ──────────────────────────────────


def test_enrich_vscode_sets_editor_fields() -> None:
    """Full enrich() path for VS Code: window_meta title + AX tree."""
    capture = {
        "window_meta": {
            "app_name": "Code",
            "title": "s1_parser.py — openchronicle [git:main] - Visual Studio Code",
            "bundle_id": "com.microsoft.VSCode",
        },
        "ax_tree": _ax_tree(
            {
                "name": "Code",
                "bundle_id": "com.microsoft.VSCode",
                "is_frontmost": True,
                "windows": [
                    {
                        "title": "s1_parser.py — openchronicle [git:main] - Visual Studio Code",
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
            }
        ),
    }
    s1_parser.enrich(capture)
    assert capture["editor_file"] == "s1_parser.py"
    assert capture["editor_project"] == "openchronicle"
    assert capture["editor_git_branch"] == "git:main"


def test_enrich_terminal_sets_cwd() -> None:
    """Full enrich() path for iTerm2."""
    import os
    home = os.path.expanduser("~")

    capture = {
        "window_meta": {
            "app_name": "iTerm2",
            "title": "vim — ~/projects/foo — zsh",
            "bundle_id": "com.googlecode.iterm2",
        },
        "ax_tree": _ax_tree(
            {
                "name": "iTerm2",
                "bundle_id": "com.googlecode.iterm2",
                "is_frontmost": True,
                "windows": [
                    {
                        "title": "vim — ~/projects/foo — zsh",
                        "focused": True,
                        "elements": [
                            {
                                "role": "AXTextArea",
                                "title": "terminal",
                                "value": "$ ls\nfile1.txt",
                            }
                        ],
                    }
                ],
            }
        ),
    }
    s1_parser.enrich(capture)
    assert capture["terminal_cwd"] == f"{home}/projects/foo"


def test_enrich_non_editor_terminal_fields_are_none() -> None:
    """Non-editor/non-terminal app gets None for all app-specific fields."""
    capture = {
        "window_meta": {
            "app_name": "Safari",
            "title": "Example",
            "bundle_id": "com.apple.Safari",
        },
        "ax_tree": _ax_tree(
            {
                "name": "Safari",
                "bundle_id": "com.apple.Safari",
                "is_frontmost": True,
                "windows": [
                    {
                        "title": "Example",
                        "focused": True,
                        "elements": [
                            {"role": "AXStaticText", "value": "some content"}
                        ],
                    }
                ],
            }
        ),
    }
    s1_parser.enrich(capture)
    assert capture["editor_file"] is None
    assert capture["editor_project"] is None
    assert capture["editor_git_branch"] is None
    assert capture["terminal_cwd"] is None
