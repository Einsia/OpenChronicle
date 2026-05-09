"""Provider discovery and loading."""

from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ProviderError
from .manifest import ProviderManifest, load_manifest
from .provider import RPAProvider


def default_providers_dir() -> Path:
    return Path(__file__).parent / "providers"


@dataclass(frozen=True)
class ProviderRegistration:
    manifest: ProviderManifest
    module_name: str
    adapter_path: Path | None = None
    class_name: str = "Provider"

    @property
    def name(self) -> str:
        return self.manifest.name

    def load(self, **kwargs: Any) -> RPAProvider:
        try:
            module = self._load_module()
            provider_cls = getattr(module, self.class_name)
            provider = provider_cls(**kwargs)
        except Exception as exc:  # noqa: BLE001 - surface provider import/init errors clearly
            raise ProviderError(f"failed to load provider {self.name!r}: {exc}") from exc
        if not isinstance(provider, RPAProvider):
            raise ProviderError(f"provider {self.name!r} does not implement RPAProvider")
        if provider.name != self.name:
            raise ProviderError(
                f"provider adapter name {provider.name!r} does not match manifest name {self.name!r}"
            )
        return provider

    def _load_module(self) -> Any:
        try:
            return importlib.import_module(self.module_name)
        except ModuleNotFoundError as exc:
            missing = exc.name or ""
            missing_provider_module = missing == self.module_name or self.module_name.startswith(
                f"{missing}."
            )
            if self.adapter_path is None or not missing_provider_module:
                raise
            return _load_module_from_path(self.module_name, self.adapter_path)


class ProviderRegistry:
    """Manifest-backed provider registry."""

    def __init__(self) -> None:
        self._providers: dict[str, ProviderRegistration] = {}

    def register(self, registration: ProviderRegistration) -> None:
        self._providers[registration.name] = registration

    def names(self) -> list[str]:
        return sorted(self._providers)

    def manifests(self) -> list[ProviderManifest]:
        return [self._providers[name].manifest for name in self.names()]

    def get(self, name: str) -> ProviderRegistration:
        try:
            return self._providers[name]
        except KeyError as exc:
            available = ", ".join(self.names()) or "none"
            raise ProviderError(f"unknown RPA provider {name!r}; available providers: {available}") from exc

    def load(self, name: str, **kwargs: Any) -> RPAProvider:
        return self.get(name).load(**kwargs)


def discover_providers(providers_dir: str | Path | None = None) -> ProviderRegistry:
    root = Path(providers_dir) if providers_dir is not None else default_providers_dir()
    registry = ProviderRegistry()
    if not root.exists():
        return registry
    for manifest_path in sorted(root.glob("*/manifest.json")):
        manifest = load_manifest(manifest_path)
        provider_dir = manifest_path.parent.name
        if manifest.name != provider_dir:
            raise ProviderError(
                f"provider manifest name {manifest.name!r} must match directory name {provider_dir!r}"
            )
        adapter_path = manifest_path.parent / "adapter.py"
        if not adapter_path.is_file():
            raise ProviderError(f"provider {manifest.name!r} is missing adapter.py")
        module_name = f"openchronicle.rpa.providers.{manifest_path.parent.name}.adapter"
        registry.register(
            ProviderRegistration(
                manifest=manifest,
                module_name=module_name,
                adapter_path=adapter_path,
            )
        )
    return registry


def _load_module_from_path(module_name: str, adapter_path: Path) -> Any:
    provider_package, _, _ = module_name.rpartition(".")
    providers_package, _, _ = provider_package.rpartition(".")
    _ensure_package(providers_package, adapter_path.parent.parent)
    _ensure_package(provider_package, adapter_path.parent)

    spec = importlib.util.spec_from_file_location(module_name, adapter_path)
    if spec is None or spec.loader is None:
        raise ProviderError(f"cannot import provider adapter {adapter_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _ensure_package(module_name: str, package_path: Path) -> None:
    module = sys.modules.get(module_name)
    if module is None:
        module = types.ModuleType(module_name)
        module.__package__ = module_name
        module.__path__ = [str(package_path)]  # type: ignore[attr-defined]
        module.__spec__ = importlib.machinery.ModuleSpec(
            module_name,
            loader=None,
            is_package=True,
        )
        sys.modules[module_name] = module
        return

    paths = getattr(module, "__path__", None)
    if paths is not None and str(package_path) not in paths:
        try:
            paths.append(str(package_path))
        except AttributeError:
            module.__path__ = [*list(paths), str(package_path)]  # type: ignore[attr-defined]
