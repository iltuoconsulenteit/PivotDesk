from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    from platformdirs import user_data_dir
except Exception:
    user_data_dir = None


APP_NAME = "PivotDesk"
APP_AUTHOR = "IlTuoConsulenteIT"

BASE_DIR = Path(__file__).resolve().parent.parent
LEGACY_CONFIG_PATH = BASE_DIR / "config.json"
LEGACY_SOURCES_PATH = BASE_DIR / "sources.json"


def _resolve_data_dir() -> Path:
    """
    Restituisce la cartella dati utente multipiattaforma.

    Priorità:
    1) variabile ambiente PIVOTDESK_DATA_DIR
    2) platformdirs (consigliato)
    3) fallback locale accanto al progetto
    """
    env_dir = os.environ.get("PIVOTDESK_DATA_DIR", "").strip()
    if env_dir:
        data_dir = Path(env_dir).expanduser().resolve()
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir

    if user_data_dir is not None:
        data_dir = Path(user_data_dir(APP_NAME, APP_AUTHOR))
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir

    fallback = BASE_DIR / "user_data"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


DATA_DIR = _resolve_data_dir()
CONFIG_PATH = DATA_DIR / "config.json"
SOURCES_PATH = DATA_DIR / "sources.json"


def _default_config() -> dict[str, Any]:
    return {
        "app_name": APP_NAME,
        "port": 8091,
        "settings": {
            "print_show_logos": True
        }
    }


def _default_sources() -> dict[str, Any]:
    return {
        "default_source": "",
        "sources": []
    }


def _normalize_config(cfg: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(cfg or {})
    cfg.setdefault("app_name", APP_NAME)
    cfg.setdefault("port", 8091)
    cfg.setdefault("settings", {})
    cfg["settings"].setdefault("print_show_logos", True)
    return cfg


def _normalize_sources(data: dict[str, Any]) -> dict[str, Any]:
    data = dict(data or {})
    data.setdefault("default_source", "")
    data.setdefault("sources", [])

    cleaned_sources: list[dict[str, Any]] = []

    for src in data.get("sources", []):
        if not isinstance(src, dict):
            continue

        sid = str(src.get("id", "")).strip()
        title = str(src.get("title", "")).strip()
        stype = str(src.get("type", "csv")).strip().lower()
        path = str(src.get("path", "")).strip()

        if not sid:
            continue

        if not title:
            title = sid

        if stype not in {"csv", "excel", "database", "xlsx", "ods", "mysql"}:
            stype = "csv"

        item = {
            "id": sid,
            "title": title,
            "type": stype,
            "path": path,
            "sheet": src.get("sheet"),
            "delimiter": src.get("delimiter"),
            "encoding": src.get("encoding"),
            "query": src.get("query"),
            "connection": src.get("connection"),
            "connection_id": src.get("connection_id"),
            "options": src.get("options") if isinstance(src.get("options"), dict) else {},
        }

        if stype in {"csv", "excel", "xlsx", "ods"} and not path:
            continue

        cleaned_sources.append(item)

    data["sources"] = cleaned_sources

    if not data["default_source"] and cleaned_sources:
        data["default_source"] = cleaned_sources[0]["id"]

    if data["default_source"] and not any(x["id"] == data["default_source"] for x in cleaned_sources):
        data["default_source"] = cleaned_sources[0]["id"] if cleaned_sources else ""

    return data


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def _migrate_legacy_file(legacy_path: Path, target_path: Path, default_factory) -> dict[str, Any]:
    """
    Se esiste il file legacy nella root progetto e il nuovo file utente non esiste,
    lo migra automaticamente.
    """
    if target_path.exists():
        return json.loads(target_path.read_text(encoding="utf-8"))

    if legacy_path.exists():
        data = json.loads(legacy_path.read_text(encoding="utf-8"))
        _write_json(target_path, data)
        return data

    data = default_factory()
    _write_json(target_path, data)
    return data


def load_config() -> dict[str, Any]:
    raw = _migrate_legacy_file(LEGACY_CONFIG_PATH, CONFIG_PATH, _default_config)
    return _normalize_config(raw)


def save_config(cfg: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_config(cfg)
    _write_json(CONFIG_PATH, normalized)
    return normalized


def load_sources() -> dict[str, Any]:
    raw = _migrate_legacy_file(LEGACY_SOURCES_PATH, SOURCES_PATH, _default_sources)
    return _normalize_sources(raw)


def save_sources(data: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_sources(data)
    _write_json(SOURCES_PATH, normalized)
    return normalized


def get_source(source_id: str | None = None) -> dict[str, Any]:
    data = load_sources()
    sources = data.get("sources", [])

    sid = str(source_id or data.get("default_source") or "").strip()
    if not sid and sources:
        sid = sources[0]["id"]

    src = next((x for x in sources if x["id"] == sid), None)
    if not src:
        raise ValueError(f"Sorgente dati non trovata: {sid or '(vuota)'}")

    return src


def get_sources_bundle() -> dict[str, Any]:
    return load_sources()


def upsert_source(payload: dict[str, Any]) -> dict[str, Any]:
    data = load_sources()

    sid = str(payload.get("id", "")).strip()
    title = str(payload.get("title", "")).strip()
    stype = str(payload.get("type", "csv")).strip().lower()
    path = str(payload.get("path", "")).strip()
    make_default = bool(payload.get("make_default", False))

    if not sid:
        raise ValueError("ID sorgente obbligatorio")

    if not title:
        title = sid

    if stype not in {"csv", "excel", "database", "xlsx", "ods", "mysql"}:
        raise ValueError(f"Tipo sorgente non supportato: {stype}")

    if stype in {"csv", "excel", "xlsx", "ods"} and not path:
        raise ValueError("Percorso file obbligatorio")

    item = {
        "id": sid,
        "title": title,
        "type": stype,
        "path": path,
        "sheet": payload.get("sheet"),
        "delimiter": payload.get("delimiter"),
        "encoding": payload.get("encoding"),
        "query": payload.get("query"),
        "connection": payload.get("connection"),
        "connection_id": payload.get("connection_id"),
        "options": payload.get("options") if isinstance(payload.get("options"), dict) else {},
    }

    replaced = False
    sources = data.get("sources", [])
    for i, src in enumerate(sources):
        if src["id"] == sid:
            sources[i] = item
            replaced = True
            break

    if not replaced:
        sources.append(item)

    data["sources"] = sources

    if make_default or not data.get("default_source"):
        data["default_source"] = sid

    return save_sources(data)


def delete_source(source_id: str) -> dict[str, Any]:
    data = load_sources()
    sid = str(source_id or "").strip()
    if not sid:
        raise ValueError("ID sorgente obbligatorio")

    sources = data.get("sources", [])
    remaining = [x for x in sources if x["id"] != sid]

    if len(remaining) == len(sources):
        raise ValueError("Sorgente dati non trovata")

    data["sources"] = remaining

    if data.get("default_source") == sid:
        data["default_source"] = remaining[0]["id"] if remaining else ""

    return save_sources(data)


def get_settings() -> dict[str, Any]:
    cfg = load_config()
    return cfg.get("settings", {})


def save_settings(payload: dict[str, Any]) -> dict[str, Any]:
    cfg = load_config()
    settings = cfg.get("settings", {})

    if "print_show_logos" in payload:
        settings["print_show_logos"] = bool(payload.get("print_show_logos"))

    cfg["settings"] = settings
    saved = save_config(cfg)
    return saved.get("settings", {})


def get_runtime_paths() -> dict[str, str]:
    """
    Utile per debug o pannello informazioni.
    """
    return {
        "base_dir": str(BASE_DIR),
        "data_dir": str(DATA_DIR),
        "config_path": str(CONFIG_PATH),
        "sources_path": str(SOURCES_PATH),
        "legacy_config_path": str(LEGACY_CONFIG_PATH),
        "legacy_sources_path": str(LEGACY_SOURCES_PATH),
    }
