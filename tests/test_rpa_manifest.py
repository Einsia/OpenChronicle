from __future__ import annotations

import json

import pytest

from openchronicle.rpa.errors import ManifestError, ProviderError
from openchronicle.rpa.manifest import load_manifest
from openchronicle.rpa.registry import discover_providers


def test_manifest_loads_builtin_android_provider() -> None:
    registry = discover_providers()

    manifest = registry.get("android_adb").manifest

    assert manifest.name == "android_adb"
    assert "tap_text" in manifest.actions
    assert "ocr" in manifest.observe


def test_manifest_missing_required_field_errors(tmp_path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"name": "broken"}), encoding="utf-8")

    with pytest.raises(ManifestError, match="missing field"):
        load_manifest(path)


def test_registry_discovers_builtin_providers() -> None:
    registry = discover_providers()

    assert registry.names() == ["android_adb", "windows_uia"]


def test_registry_loads_provider_from_manifest_and_adapter_only(tmp_path) -> None:
    provider_dir = tmp_path / "providers" / "example_provider"
    provider_dir.mkdir(parents=True)
    (provider_dir / "manifest.json").write_text(
        json.dumps(
            {
                "name": "example_provider",
                "type": "test_rpa",
                "platform": ["test"],
                "actions": ["wait"],
                "observe": ["state"],
                "safety_level": "low",
                "requires_confirmation": [],
                "memory_output": ["trace"],
            }
        ),
        encoding="utf-8",
    )
    (provider_dir / "adapter.py").write_text(
        "\n".join(
            [
                "from openchronicle.rpa.provider import RPAProvider",
                "",
                "class Provider(RPAProvider):",
                "    name = 'example_provider'",
                "    platform = 'test'",
                "    def observe(self):",
                "        return {'ok': True, 'provider': self.name, 'platform': self.platform, 'errors': []}",
                "    def act(self, action):",
                "        return {'ok': True, 'status': 'success', 'message': 'ok', 'action': action}",
                "    def capabilities(self):",
                "        return {'actions': ['wait'], 'observe': ['state']}",
            ]
        ),
        encoding="utf-8",
    )

    registry = discover_providers(tmp_path / "providers")
    provider = registry.load("example_provider")

    assert registry.names() == ["example_provider"]
    assert provider.observe()["provider"] == "example_provider"
    assert not (provider_dir / "__init__.py").exists()


def test_registry_unknown_provider_error_lists_available() -> None:
    registry = discover_providers()

    with pytest.raises(ProviderError, match="unknown RPA provider 'missing'.*android_adb"):
        registry.load("missing")
