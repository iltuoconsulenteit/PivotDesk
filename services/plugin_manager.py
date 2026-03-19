from __future__ import annotations

import importlib.util
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class PluginManifest:
    id: str
    name: str
    version: str = "0.1.0"
    description: str = ""
    enabled: bool = True
    frontend: dict[str, Any] = field(default_factory=dict)


@dataclass
class LoadedPlugin:
    manifest: PluginManifest
    base_path: Path
    module: Any | None = None
    backend_registered: bool = False
    frontend_payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class PluginAPI:
    """
    API controllata esposta ai plugin.
    Aggiungi qui, in modo graduale, solo le funzioni del core che vuoi rendere pubbliche.
    """

    def __init__(
        self,
        *,
        get_source: Callable[..., Any] | None = None,
        load_dataframe_from_source: Callable[..., Any] | None = None,
        get_sources_bundle: Callable[..., Any] | None = None,
        get_runtime_paths: Callable[..., Any] | None = None,
    ) -> None:
        self.get_source = get_source
        self.load_dataframe_from_source = load_dataframe_from_source
        self.get_sources_bundle = get_sources_bundle
        self.get_runtime_paths = get_runtime_paths


class PluginManager:
    def __init__(
        self,
        plugins_dir: str | Path,
        *,
        enabled_map: dict[str, bool] | None = None,
    ) -> None:
        self.plugins_dir = Path(plugins_dir)
        self.enabled_map = enabled_map or {}
        self.loaded_plugins: dict[str, LoadedPlugin] = {}

    def discover_plugin_dirs(self) -> list[Path]:
        if not self.plugins_dir.exists():
            return []
        return sorted(
            p for p in self.plugins_dir.iterdir()
            if p.is_dir() and (p / "manifest.json").exists()
        )

    def _read_manifest(self, path: Path) -> PluginManifest:
        raw = json.loads(path.read_text(encoding="utf-8"))
        plugin_id = str(raw.get("id", "")).strip()
        if not plugin_id:
            raise ValueError(f"Manifest non valido: manca id ({path})")

        manifest = PluginManifest(
            id=plugin_id,
            name=str(raw.get("name", plugin_id)).strip() or plugin_id,
            version=str(raw.get("version", "0.1.0")).strip() or "0.1.0",
            description=str(raw.get("description", "")).strip(),
            enabled=bool(raw.get("enabled", True)),
            frontend=raw.get("frontend", {}) if isinstance(raw.get("frontend", {}), dict) else {},
        )
        if plugin_id in self.enabled_map:
            manifest.enabled = bool(self.enabled_map[plugin_id])
        return manifest

    def _load_module(self, plugin_dir: Path):
        plugin_file = plugin_dir / "plugin.py"
        if not plugin_file.exists():
            return None

        module_name = f"pivotdesk_plugin_{plugin_dir.name}"
        spec = importlib.util.spec_from_file_location(module_name, plugin_file)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Impossibile caricare plugin.py per {plugin_dir.name}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def load_all(self, app: Any, plugin_api: PluginAPI) -> dict[str, LoadedPlugin]:
        self.loaded_plugins = {}

        for plugin_dir in self.discover_plugin_dirs():
            manifest_path = plugin_dir / "manifest.json"
            try:
                manifest = self._read_manifest(manifest_path)
                loaded = LoadedPlugin(manifest=manifest, base_path=plugin_dir)

                if not manifest.enabled:
                    self.loaded_plugins[manifest.id] = loaded
                    continue

                module = self._load_module(plugin_dir)
                loaded.module = module

                if module and hasattr(module, "register"):
                    result = module.register(app, plugin_api, manifest)
                    loaded.backend_registered = True
                    if isinstance(result, dict):
                        loaded.frontend_payload = result
                else:
                    loaded.frontend_payload = manifest.frontend or {}

                self.loaded_plugins[manifest.id] = loaded
                logger.info("Plugin caricato: %s", manifest.id)

            except Exception as exc:
                plugin_id = plugin_dir.name
                logger.exception("Errore caricamento plugin %s", plugin_id)
                self.loaded_plugins[plugin_id] = LoadedPlugin(
                    manifest=PluginManifest(id=plugin_id, name=plugin_id, enabled=False),
                    base_path=plugin_dir,
                    error=str(exc),
                )

        return self.loaded_plugins

    def get_frontend_registry(self) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        for plugin_id, plugin in self.loaded_plugins.items():
            items.append({
                "id": plugin_id,
                "name": plugin.manifest.name,
                "version": plugin.manifest.version,
                "enabled": plugin.manifest.enabled,
                "description": plugin.manifest.description,
                "frontend": plugin.frontend_payload or plugin.manifest.frontend or {},
                "error": plugin.error,
            })
        return {"items": items}

    def get_status(self) -> dict[str, Any]:
        return {
            "plugins_dir": str(self.plugins_dir),
            "count": len(self.loaded_plugins),
            "items": [
                {
                    "id": p.manifest.id,
                    "name": p.manifest.name,
                    "enabled": p.manifest.enabled,
                    "backend_registered": p.backend_registered,
                    "error": p.error,
                    "path": str(p.base_path),
                }
                for p in self.loaded_plugins.values()
            ]
        }
