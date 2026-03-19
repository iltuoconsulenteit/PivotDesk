from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from services.adapters.source_factory import build_source_adapter
from services.config_loader import DATA_DIR

BASE_DIR = Path(__file__).resolve().parent.parent
LEGACY_DATA_DIR = BASE_DIR / "data"
LEGACY_CONNECTIONS_PATH = LEGACY_DATA_DIR / "connections.json"
CONNECTIONS_PATH = DATA_DIR / "connections.json"


def _default_connections() -> dict[str, Any]:
    return {"items": []}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def _migrate_legacy_connections() -> dict[str, Any]:
    """
    Migra automaticamente connections.json dalla vecchia cartella data/
    alla nuova cartella dati utente.
    """
    if CONNECTIONS_PATH.exists():
        try:
            return json.loads(CONNECTIONS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return _default_connections()

    if LEGACY_CONNECTIONS_PATH.exists():
        try:
            data = json.loads(LEGACY_CONNECTIONS_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = _default_connections()
        _write_json(CONNECTIONS_PATH, data)
        return data

    data = _default_connections()
    _write_json(CONNECTIONS_PATH, data)
    return data


def _read_connections() -> dict[str, Any]:
    try:
        data = _migrate_legacy_connections()
        if not isinstance(data, dict):
            return _default_connections()
        data.setdefault("items", [])
        if not isinstance(data.get("items"), list):
            data["items"] = []
        return data
    except Exception:
        return _default_connections()


def get_connections_bundle() -> dict[str, Any]:
    return _read_connections()


def save_connections_bundle(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload or {})
    items = data.get("items", [])
    if not isinstance(items, list):
        items = []
    normalized = {"items": items}
    _write_json(CONNECTIONS_PATH, normalized)
    return normalized


def load_dataframe_from_source(source: dict[str, Any]) -> pd.DataFrame:
    connections = _read_connections()
    adapter = build_source_adapter(source, connections)
    return adapter.load_dataframe()


def get_runtime_connection_paths() -> dict[str, str]:
    return {
        "connections_path": str(CONNECTIONS_PATH),
        "legacy_connections_path": str(LEGACY_CONNECTIONS_PATH),
        "data_dir": str(DATA_DIR),
    }
