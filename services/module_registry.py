from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ModuleManifest:
    id: str
    name: str
    description: str = ""
    kind: str = "core"
    plugin_id: str = ""
    enabled: bool = True
    version: str = "1.0.0"
    ui: dict[str, Any] | None = None
    path: str = ""


class ModuleRegistry:
    """
    Registro moduli applicativi (separato dal registro plugin).
    I moduli rappresentano funzionalità/pagine; i plugin estendono i moduli.
    """

    def __init__(self, modules_dir: str | Path | list[str | Path] | tuple[str | Path, ...]) -> None:
        if isinstance(modules_dir, (list, tuple)):
            self.modules_dirs = [Path(p) for p in modules_dir]
        else:
            self.modules_dirs = [Path(modules_dir)]
        self.manifests: list[ModuleManifest] = []

    def discover_module_manifests(self) -> list[Path]:
        found: list[Path] = []
        for root in self.modules_dirs:
            if not root.exists():
                continue
            for module_dir in sorted(root.iterdir()):
                if not module_dir.is_dir():
                    continue
                manifest = module_dir / "module.json"
                if manifest.exists():
                    found.append(manifest)
        return found

    def load_all(self) -> list[ModuleManifest]:
        loaded: list[ModuleManifest] = []
        for manifest_path in self.discover_module_manifests():
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            module_id = str(raw.get("id", "")).strip()
            if not module_id:
                continue
            loaded.append(
                ModuleManifest(
                    id=module_id,
                    name=str(raw.get("name") or module_id).strip() or module_id,
                    description=str(raw.get("description") or "").strip(),
                    kind=str(raw.get("kind") or "core").strip() or "core",
                    plugin_id=str(raw.get("plugin_id") or "").strip(),
                    enabled=bool(raw.get("enabled", True)),
                    version=str(raw.get("version") or "1.0.0").strip() or "1.0.0",
                    ui=raw.get("ui") if isinstance(raw.get("ui"), dict) else None,
                    path=str(manifest_path.parent),
                )
            )
        self.manifests = loaded
        return loaded

    def get_status(self) -> dict[str, Any]:
        return {
            "modules_dirs": [str(p) for p in self.modules_dirs],
            "count": len(self.manifests),
            "items": [
                {
                    "id": m.id,
                    "name": m.name,
                    "description": m.description,
                    "kind": m.kind,
                    "plugin_id": m.plugin_id,
                    "enabled": m.enabled,
                    "version": m.version,
                    "ui": m.ui or {},
                    "path": m.path,
                }
                for m in self.manifests
            ],
        }
