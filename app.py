from __future__ import annotations

import json
import csv
import logging
import os
import re
import sys
import platform
import hashlib
import shutil
import subprocess
import uuid
import time
import sqlite3
from io import BytesIO, StringIO
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, Query, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from services.pivot_engine import apply_filters, normalize_df, run_pivot, table_to_html
from services.source_manager import load_dataframe_from_source
from services.plugin_manager import PluginAPI, PluginManager
from plugins.calculated_fields.backend import (
    apply_calculated_fields,
    build_calculated_definitions,
)

logger = logging.getLogger("pivotdesk.app")
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

try:
    from licensing.license_manager_multistore import (
        LicenseManager,
        LicenseManagerConfig,
        DeveloperProvider,
        DeveloperConfig,
        GumroadProvider,
        GumroadConfig,
        LemonSqueezyProvider,
        LemonSqueezyConfig,
        CustomProvider,
        CustomConfig,
    )
    MULTISTORE_LICENSE_AVAILABLE = True
except Exception:
    LicenseManager = None
    LicenseManagerConfig = None
    DeveloperProvider = None
    DeveloperConfig = None
    GumroadProvider = None
    GumroadConfig = None
    LemonSqueezyProvider = None
    LemonSqueezyConfig = None
    CustomProvider = None
    CustomConfig = None
    MULTISTORE_LICENSE_AVAILABLE = False

def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


BASE_DIR = Path(__file__).resolve().parent
RUNTIME_BASE_DIR = Path(sys.executable).resolve().parent if is_frozen() else BASE_DIR
RESOURCE_BASE_DIR = (
    Path(getattr(sys, "_MEIPASS")).resolve()
    if is_frozen() and hasattr(sys, "_MEIPASS")
    else BASE_DIR
)


def resource_path(*parts: str) -> Path:
    return RESOURCE_BASE_DIR.joinpath(*parts)

APP_HOME_DIR = Path(os.getenv("APPDATA", str(RUNTIME_BASE_DIR))) / "PivotDesk" if is_frozen() else BASE_DIR
if is_frozen():
    # In packaged runtime, prefer sibling folders near the executable so
    # hotfixes can be delivered without rebuilding the entire binary.
    STATIC_DIR = RUNTIME_BASE_DIR / "static"
    TEMPLATES_DIR = RUNTIME_BASE_DIR / "templates"
else:
    STATIC_DIR = BASE_DIR / "static"
    TEMPLATES_DIR = BASE_DIR / "templates"
if not STATIC_DIR.exists():
    STATIC_DIR = BASE_DIR / "static"
if not STATIC_DIR.exists():
    STATIC_DIR = RESOURCE_BASE_DIR / "static"
if not TEMPLATES_DIR.exists():
    TEMPLATES_DIR = BASE_DIR / "templates"
if not TEMPLATES_DIR.exists():
    TEMPLATES_DIR = RESOURCE_BASE_DIR / "templates"
DATA_DIR = APP_HOME_DIR / "data"
PIVOTS_DIR = APP_HOME_DIR / "pivots"
LEGACY_PIVOTS_DIR = BASE_DIR / "pivots"

CONFIG_PATH = DATA_DIR / "config.json"
SETTINGS_PATH = DATA_DIR / "settings.json"
SOURCES_PATH = DATA_DIR / "sources.json"
PLUGINS_CONFIG_PATH = DATA_DIR / "plugins.json"
LEGACY_SOURCES_PATH = BASE_DIR / "sources.json"
IMPORT_DATA_DIR = DATA_DIR / "import_data"
LEGACY_PLUGINS_CONFIG_PATH = BASE_DIR / "plugins.json"
USERS_PATH = DATA_DIR / "users.json"
LICENSE_SETTINGS_PATH = DATA_DIR / "license_settings.json"
BRANDING_DIR = DATA_DIR / "branding"
CUSTOMER_LOGO_PATH = BRANDING_DIR / "customer_logo.png"
CUSTOMER_LOGO_META_PATH = BRANDING_DIR / "customer_logo.json"

LICENSES_DIR = BASE_DIR / "licenses"
if not LICENSES_DIR.exists():
    LICENSES_DIR = RESOURCE_BASE_DIR / "licenses"
APPDATA_LICENSE_DIR = Path(os.getenv("APPDATA", str(BASE_DIR))) / "PivotDesk"
APPDATA_LICENSE_PATH = APPDATA_LICENSE_DIR / "license.json"
DEMO_LICENSE_PATH = LICENSES_DIR / "demo-license.json"
DEV_LICENSE_PATH = LICENSES_DIR / "dev-license.json"

DEFAULT_CONFIG = {
    "app_name": "PivotDesk",
    "host": "127.0.0.1",
    "port": 8091,
}

DEFAULT_SETTINGS = {
    "print_show_logos": True,
    "language": "en",
    "pivot_case_sensitive": False,
}

DEFAULT_SOURCES = {
    "default_source": "",
    "items": [],
}

SOURCE_DATAFRAME_CACHE_TTL_SEC = 90
SOURCE_DATAFRAME_CACHE_MAX_ENTRIES = 12
SOURCE_DATAFRAME_CACHE_MAX_TOTAL_MB = 256
SOURCE_DATAFRAME_CACHE_MAX_ENTRY_MB = 64
_SOURCE_DATAFRAME_CACHE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()

DEFAULT_LICENSE_SETTINGS = {
    "license_file": str(APPDATA_LICENSE_PATH),
    "developer": {
        "enabled": True,
        "allowed_keys": ["PIVOTDESK-DEV", "PIVOTDESK-DEVELOPER"],
        "offline_days": 3650,
        "customer_name": "Developer",
        "customer_email": "dev@local",
    },
    "gumroad": {
        "enabled": False,
        "product_id": "",
        "increment_uses_count": False,
        "offline_days": 14,
        "timeout": 20,
        "extra_features": {"plugins": True, "charts": True, "advanced_import": True},
    },
    "lemonsqueezy": {
        "enabled": False,
        "product_id": "",
        "variant_id": "",
        "offline_days": 14,
        "timeout": 20,
        "extra_features": {"plugins": True, "charts": True, "advanced_import": True},
    },
    "custom": {
        "enabled": False,
        "activate_url": "",
        "validate_url": "",
        "deactivate_url": "",
        "api_key": "",
        "timeout": 20,
    },
}

DEFAULT_LICENSE_FEATURES = {
    "subtotals": False,
    "preview": False,
    "print": False,
    "backup_restore": False,
    "charts": False,
    "drilldown": False,
    "plugins": False,
}

DEFAULT_DEV_FEATURES = {
    "subtotals": True,
    "preview": True,
    "print": True,
    "backup_restore": True,
    "charts": True,
    "drilldown": True,
    "plugins": True,
}


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def ensure_json_file(path: Path, default_data: Any) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(default_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


ensure_dir(DATA_DIR)
ensure_dir(PIVOTS_DIR)
ensure_dir(LICENSES_DIR)
ensure_dir(APPDATA_LICENSE_DIR)
ensure_dir(IMPORT_DATA_DIR)
ensure_json_file(CONFIG_PATH, DEFAULT_CONFIG)
ensure_json_file(SETTINGS_PATH, DEFAULT_SETTINGS)
ensure_json_file(SOURCES_PATH, DEFAULT_SOURCES)
ensure_json_file(LICENSE_SETTINGS_PATH, DEFAULT_LICENSE_SETTINGS)

ensure_json_file(
    USERS_PATH,
    {
        "items": [
            {
                "username": "admin",
                "display_name": "Administrator",
                "role": "admin",
                "enabled": True,
                "password_hash": hashlib.sha256("admin".encode("utf-8")).hexdigest(),
            }
        ]
    },
)

LAN_PROBES: dict[str, dict[str, Any]] = {}

app = FastAPI(title="PivotDesk")
app.add_middleware(SessionMiddleware, secret_key="pivotdesk-dev-secret-change-me", same_site="lax", https_only=False)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.on_event("startup")
async def _pivotdesk_startup_enforce_lan_bind():
    try:
        load_sources_data()
    except Exception:
        pass
    maybe_force_lan_rebind_on_startup()


def read_json(path: Path, fallback: Any) -> Any:
    try:
        if not path.exists():
            return fallback
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _normalize_sep_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() in {"auto", "automatic", "automatico"}:
        return None

    aliases = {
        "\\t": "\t",
        "\t": "\t",
        "tab": "\t",
        "virgola": ",",
        "comma": ",",
        "punto e virgola": ";",
        "punto_e_virgola": ";",
        "semicolon": ";",
        "pipe": "|",
        "barra verticale": "|",
        "barra_verticale": "|",
    }
    return aliases.get(text.lower(), text)


def _sniff_csv_delimiter(sample: str, skip_rows: int = 0) -> str:
    candidates = [",", ";", "\t", "|"]
    lines = sample.splitlines()
    if skip_rows and skip_rows > 0:
        lines = lines[int(skip_rows):]

    non_empty = [ln for ln in lines if ln.strip()]
    if not non_empty:
        return ";"

    text = "\n".join(non_empty[:25])

    try:
        dialect = csv.Sniffer().sniff(text, delimiters="".join(candidates))
        if dialect and dialect.delimiter in candidates:
            return dialect.delimiter
    except Exception:
        pass

    def _score(delim: str) -> tuple[int, int, int]:
        counts = []
        for line in non_empty[:25]:
            try:
                row = next(csv.reader([line], delimiter=delim, quotechar='"'))
                counts.append(len(row))
            except Exception:
                counts.append(1)
        if not counts:
            return (0, 0, 0)
        max_cols = max(counts)
        consistent = sum(1 for c in counts if c == max_cols and c > 1)
        multi = sum(1 for c in counts if c > 1)
        return (consistent, multi, max_cols)

    best = max(candidates, key=_score)
    return best or ";"


def _read_csv_local(path: str, delimiter: Any = None, encoding: Any = None, skip_rows: int = 0) -> tuple[pd.DataFrame, str, str]:
    encodings: list[str] = []
    enc = str(encoding or "").strip()
    if enc:
        encodings.append(enc)
    for fallback in ["utf-8-sig", "utf-8", "cp1252", "latin1"]:
        if fallback not in encodings:
            encodings.append(fallback)

    last_error: Exception | None = None
    sep = _normalize_sep_value(delimiter)
    skip_rows = max(int(skip_rows or 0), 0)

    def _df_score(df: pd.DataFrame) -> tuple[int, int, int]:
        cols = int(len(df.columns))
        rows = int(len(df))
        non_empty_cols = sum(1 for c in df.columns if str(c).strip())
        return (cols, min(rows, 100), non_empty_cols)

    def _read_csv_tolerant(actual_sep: str, enc_name: str) -> pd.DataFrame:
        def _clean_csv_token(value: Any) -> str:
            text = "" if value is None else str(value)
            if text in {"", "nan", "None"}:
                return ""

            if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
                q = text[0]
                inner = text[1:-1]
                if q == '"':
                    inner = inner.replace('""', '"').replace('\\"', '"')
                else:
                    inner = inner.replace("''", "'").replace("\\'", "'")
                return inner

            return text

        def _cleanup_dataframe(df_in: pd.DataFrame) -> pd.DataFrame:
            cleaned = df_in.copy()
            cleaned.columns = [_clean_csv_token(c) for c in cleaned.columns]
            for col in cleaned.columns:
                cleaned[col] = cleaned[col].map(_clean_csv_token)
            return cleaned

        base_kwargs = {
            "filepath_or_buffer": path,
            "sep": actual_sep,
            "encoding": enc_name,
            "skiprows": skip_rows,
            "dtype": str,
            "keep_default_na": False,
            "engine": "python",
        }
        attempts = [
            {"quotechar": '"', "doublequote": True},
            {"quotechar": '"', "doublequote": False, "escapechar": "\\"},
            {"quoting": csv.QUOTE_NONE, "escapechar": "\\"},
            {"quoting": csv.QUOTE_NONE, "on_bad_lines": "skip"},
        ]

        last_exc: Exception | None = None
        for extra in attempts:
            try:
                parsed = pd.read_csv(**base_kwargs, **extra)
                return _cleanup_dataframe(parsed)
            except Exception as exc:
                last_exc = exc

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Impossibile leggere il CSV con i parser disponibili")

    # Se l'utente ha scelto manualmente un delimitatore, quello deve vincere sempre.
    if sep:
        for enc_name in encodings:
            try:
                df = _read_csv_tolerant(sep, enc_name)
                return df, sep, enc_name
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"Impossibile leggere il CSV locale con il delimitatore selezionato: {last_error}")

    best_result: tuple[pd.DataFrame, str, str] | None = None
    best_score: tuple[int, int, int] | None = None

    for enc_name in encodings:
        try:
            with open(path, "r", encoding=enc_name, errors="replace", newline="") as fh:
                sample = fh.read(16384)
        except Exception as exc:
            last_error = exc
            continue

        candidates: list[str] = []
        guessed = _sniff_csv_delimiter(sample, skip_rows=skip_rows)
        if guessed:
            candidates.append(guessed)

        for fallback_sep in [";", ",", "\t", "|"]:
            if fallback_sep not in candidates:
                candidates.append(fallback_sep)

        for actual_sep in candidates:
            try:
                df = _read_csv_tolerant(actual_sep, enc_name)
            except Exception as exc:
                last_error = exc
                continue

            score = _df_score(df)
            if best_result is None or score > best_score:
                best_result = (df, actual_sep, enc_name)
                best_score = score

    if best_result is not None:
        return best_result

    raise RuntimeError(f"Impossibile leggere il CSV locale: {last_error}")


def _read_excel_local(path: str, sheet_name: Any = None, skip_rows: int = 0) -> tuple[pd.DataFrame, str]:
    sheet = str(sheet_name).strip() if sheet_name is not None else ""
    target_sheet: Any = 0 if sheet == "" else sheet
    df = pd.read_excel(
        path,
        sheet_name=target_sheet,
        skiprows=max(int(skip_rows or 0), 0),
        dtype=str,
    )
    resolved_sheet = "primo foglio" if target_sheet == 0 else str(target_sheet)
    return df, resolved_sheet


def load_dataframe_from_source_with_fallback(source: dict[str, Any]) -> pd.DataFrame:
    src_type = str(source.get("type", "")).strip().lower()
    path = str(source.get("path") or source.get("config", {}).get("path") or "").strip()
    cfg = source.get("config", {}) if isinstance(source.get("config"), dict) else {}
    delimiter = source.get("delimiter", cfg.get("delimiter"))
    encoding = source.get("encoding", cfg.get("encoding"))
    sheet_name = source.get("sheet_name", cfg.get("sheet_name", cfg.get("sheet")))
    skip_rows = source.get("skip_rows", cfg.get("skip_rows", 0))

    if src_type in {"csv"} and path:
        df, actual_sep, actual_encoding = _read_csv_local(path, delimiter=delimiter, encoding=encoding, skip_rows=skip_rows)
        source["delimiter"] = actual_sep
        source["encoding"] = actual_encoding
        cfg["delimiter"] = actual_sep
        cfg["encoding"] = actual_encoding
        cfg["skip_rows"] = max(int(skip_rows or 0), 0)
        source["config"] = cfg
        return df.fillna("")

    if src_type in {"xlsx", "xls", "xlsm"} and path:
        df, resolved_sheet = _read_excel_local(path, sheet_name=sheet_name, skip_rows=skip_rows)
        source["sheet_name"] = "" if resolved_sheet == "primo foglio" else resolved_sheet
        cfg["sheet_name"] = source["sheet_name"]
        cfg["skip_rows"] = max(int(skip_rows or 0), 0)
        source["config"] = cfg
        return df.fillna("")

    df = load_dataframe_from_source(source)
    if df is None or not isinstance(df, pd.DataFrame):
        raise RuntimeError("Impossibile leggere la sorgente dati con i parametri indicati")
    return df.fillna("")



def load_config() -> dict[str, Any]:
    data = read_json(CONFIG_PATH, DEFAULT_CONFIG.copy()) or {}
    out = DEFAULT_CONFIG.copy()
    out.update(data)
    return out


def load_settings_data() -> dict[str, Any]:
    data = read_json(SETTINGS_PATH, DEFAULT_SETTINGS.copy()) or {}
    out = DEFAULT_SETTINGS.copy()
    out.update(data)
    out["language"] = str(out.get("language", "en")).strip().lower()
    if out["language"] not in {"it", "en"}:
        out["language"] = "en"
    out["pivot_case_sensitive"] = bool(out.get("pivot_case_sensitive", False))
    return out


def save_settings_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = DEFAULT_SETTINGS.copy()
    data.update(payload or {})
    lang = str(data.get("language", "en")).strip().lower()
    if lang not in {"it", "en"}:
        lang = "en"
    data["language"] = lang
    data["pivot_case_sensitive"] = bool(data.get("pivot_case_sensitive", False))
    write_json(SETTINGS_PATH, data)
    return data



def load_license_settings() -> dict[str, Any]:
    data = read_json(LICENSE_SETTINGS_PATH, DEFAULT_LICENSE_SETTINGS.copy()) or {}
    merged = json.loads(json.dumps(DEFAULT_LICENSE_SETTINGS))
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key].update(value)
            else:
                merged[key] = value
    if not merged.get("license_file"):
        merged["license_file"] = str(APPDATA_LICENSE_PATH)
    return merged


def build_license_manager() -> LicenseManager | None:
    if not MULTISTORE_LICENSE_AVAILABLE:
        return None

    settings = load_license_settings()
    providers: dict[str, Any] = {}

    dev_cfg = settings.get("developer", {}) if isinstance(settings.get("developer"), dict) else {}
    if dev_cfg.get("enabled", True):
        providers["developer"] = DeveloperProvider(
            DeveloperConfig(
                allowed_keys=tuple(dev_cfg.get("allowed_keys") or ["PIVOTDESK-DEV"]),
                offline_days=int(dev_cfg.get("offline_days", 3650) or 3650),
                customer_name=str(dev_cfg.get("customer_name") or "Developer"),
                customer_email=str(dev_cfg.get("customer_email") or "dev@local"),
            )
        )

    gum_cfg = settings.get("gumroad", {}) if isinstance(settings.get("gumroad"), dict) else {}
    if gum_cfg.get("enabled") and str(gum_cfg.get("product_id") or "").strip():
        providers["gumroad"] = GumroadProvider(
            GumroadConfig(
                product_id=str(gum_cfg.get("product_id") or "").strip(),
                increment_uses_count=bool(gum_cfg.get("increment_uses_count", False)),
                offline_days=int(gum_cfg.get("offline_days", 14) or 14),
                timeout=int(gum_cfg.get("timeout", 20) or 20),
                extra_features=gum_cfg.get("extra_features", {}) if isinstance(gum_cfg.get("extra_features"), dict) else {},
            )
        )

    ls_cfg = settings.get("lemonsqueezy", {}) if isinstance(settings.get("lemonsqueezy"), dict) else {}
    if ls_cfg.get("enabled") and str(ls_cfg.get("product_id") or "").strip():
        providers["lemonsqueezy"] = LemonSqueezyProvider(
            LemonSqueezyConfig(
                product_id=str(ls_cfg.get("product_id") or "").strip(),
                variant_id=str(ls_cfg.get("variant_id") or "").strip() or None,
                offline_days=int(ls_cfg.get("offline_days", 14) or 14),
                timeout=int(ls_cfg.get("timeout", 20) or 20),
                extra_features=ls_cfg.get("extra_features", {}) if isinstance(ls_cfg.get("extra_features"), dict) else {},
            )
        )

    custom_cfg = settings.get("custom", {}) if isinstance(settings.get("custom"), dict) else {}
    if custom_cfg.get("enabled") and str(custom_cfg.get("activate_url") or "").strip() and str(custom_cfg.get("validate_url") or "").strip() and str(custom_cfg.get("deactivate_url") or "").strip():
        providers["custom"] = CustomProvider(
            CustomConfig(
                activate_url=str(custom_cfg.get("activate_url") or "").strip(),
                validate_url=str(custom_cfg.get("validate_url") or "").strip(),
                deactivate_url=str(custom_cfg.get("deactivate_url") or "").strip(),
                api_key=str(custom_cfg.get("api_key") or "").strip() or None,
                timeout=int(custom_cfg.get("timeout", 20) or 20),
            )
        )

    if not providers:
        return None

    return LicenseManager(
        providers=providers,
        config=LicenseManagerConfig(license_file=str(settings.get("license_file") or APPDATA_LICENSE_PATH)),
    )


def get_available_license_providers() -> list[str]:
    manager = build_license_manager()
    if not manager:
        return []
    return sorted(manager.providers.keys())


def _license_context_from_record(record: Any, message: str | None = None) -> dict[str, Any]:
    features = dict(DEFAULT_LICENSE_FEATURES)
    if getattr(record, "features", None):
        features.update(record.features)
    edition = str(getattr(record, "edition", "full") or "full")
    status = str(getattr(record, "status", "active") or "active").lower()
    license_payload = {
        "provider": getattr(record, "provider", None),
        "product": "PivotDesk",
        "edition": edition.title(),
        "license_type": edition.lower(),
        "license_id": getattr(record, "instance_id", None) or getattr(record, "license_key", ""),
        "customer_name": getattr(record, "customer_name", None),
        "customer_email": getattr(record, "customer_email", None),
        "issued_at": getattr(record, "activated_at", None) or getattr(record, "last_validated_at", None),
        "expires_at": getattr(record, "expires_at", None),
        "maintenance_until": getattr(record, "maintenance_until", None),
        "features": features,
        "status": status,
        "message": message or "",
    }
    return {
        "license": license_payload,
        "license_status": edition.lower(),
        "license_features": features,
        "license_is_demo": False,
        "license_is_dev": edition.lower() == "developer",
        "license_label": license_payload["edition"],
        "license_provider": getattr(record, "provider", None),
        "license_remote_status": status,
        "license_message": message or "",
    }


def try_multistore_license_context(prefer_online: bool = False) -> dict[str, Any] | None:
    manager = build_license_manager()
    if not manager:
        return None

    try:
        record = manager.load()
    except Exception:
        record = None

    if not record:
        return None

    try:
        result = manager.validate_current(prefer_online=prefer_online)
    except Exception as exc:
        return {
            **_license_context_from_record(record, f"Licenza locale presente ma verifica non riuscita: {exc}"),
            "license_warning": True,
        }

    if result.record:
        return _license_context_from_record(result.record, result.message)

    return {
        **_license_context_from_record(record, result.message),
        "license_warning": True,
        "license_remote_status": result.error_code or "invalid",
    }



def hash_password(password: str) -> str:
    return hashlib.sha256(str(password).encode("utf-8")).hexdigest()


def load_users_data() -> dict[str, Any]:
    data = read_json(USERS_PATH, {"items": []}) or {"items": []}
    if not isinstance(data.get("items"), list):
        data["items"] = []
    return data


def save_users_data(data: dict[str, Any]) -> dict[str, Any]:
    write_json(USERS_PATH, data)
    return data


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "username": str(user.get("username", "")).strip(),
        "display_name": str(user.get("display_name", "")).strip(),
        "role": str(user.get("role", "user")).strip() or "user",
        "enabled": bool(user.get("enabled", True)),
    }


def find_user(username: str | None) -> dict[str, Any] | None:
    uname = str(username or "").strip().lower()
    if not uname:
        return None
    for user in load_users_data().get("items", []):
        if str(user.get("username", "")).strip().lower() == uname:
            return user
    return None


def get_current_user_from_session(request: Request) -> dict[str, Any] | None:
    username = request.session.get("username")
    user = find_user(username)
    if not user or not bool(user.get("enabled", True)):
        return None
    return public_user(user)


def require_login(request: Request) -> dict[str, Any] | None:
    return get_current_user_from_session(request)


def require_admin(request: Request) -> dict[str, Any] | None:
    user = get_current_user_from_session(request)
    if not user:
        return None
    if str(user.get("role", "user")).lower() != "admin":
        return None
    return user

def is_dev_runtime() -> bool:
    return not getattr(sys, "frozen", False)


def build_demo_license() -> dict[str, Any]:
    return {
        "vendor": "IlTuoConsulenteIT",
        "product": "PivotDesk",
        "edition": "Demo",
        "license_type": "demo",
        "license_id": "PD-DEMO-LOCAL",
        "customer_name": "Demo User",
        "customer_email": "demo@local",
        "issued_at": datetime.now().strftime("%Y-%m-%d"),
        "features": DEFAULT_LICENSE_FEATURES.copy(),
    }


def build_dev_license() -> dict[str, Any]:
    return {
        "vendor": "IlTuoConsulenteIT",
        "product": "PivotDesk",
        "edition": "Developer",
        "license_type": "dev",
        "license_id": "PD-DEV-LOCAL",
        "customer_name": "Developer",
        "customer_email": "dev@local",
        "issued_at": datetime.now().strftime("%Y-%m-%d"),
        "features": DEFAULT_DEV_FEATURES.copy(),
    }


def normalize_license_payload(data: dict[str, Any] | None) -> dict[str, Any]:
    lic = dict(data or {})
    features = lic.get("features") if isinstance(lic.get("features"), dict) else {}
    merged = DEFAULT_LICENSE_FEATURES.copy()
    merged.update(features)
    lic["features"] = merged
    return lic


def load_license_payload() -> dict[str, Any]:
    lic = read_json(APPDATA_LICENSE_PATH, None)
    if isinstance(lic, dict) and lic.get("product") == "PivotDesk":
        return normalize_license_payload(lic)

    multistore_ctx = try_multistore_license_context(prefer_online=False)
    if multistore_ctx and isinstance(multistore_ctx.get("license"), dict):
        return normalize_license_payload(multistore_ctx["license"])

    if is_dev_runtime():
        lic = read_json(DEV_LICENSE_PATH, None)
        if isinstance(lic, dict) and lic.get("product") == "PivotDesk":
            return normalize_license_payload(lic)

    lic = read_json(DEMO_LICENSE_PATH, None)
    if isinstance(lic, dict) and lic.get("product") == "PivotDesk":
        return normalize_license_payload(lic)

    data = build_demo_license()
    write_json(DEMO_LICENSE_PATH, data)
    return normalize_license_payload(data)


def get_license_context(prefer_online: bool = False) -> dict[str, Any]:
    multistore_ctx = try_multistore_license_context(prefer_online=prefer_online)
    if multistore_ctx:
        multistore_ctx.setdefault("license_purchase_url", "")
        multistore_ctx.setdefault("customer_logo_url", get_customer_logo_url() if CUSTOMER_LOGO_PATH.exists() else "")
        return multistore_ctx

    lic = load_license_payload()
    status = str(lic.get("license_type", "demo")).strip().lower() or "demo"
    features = lic.get("features") if isinstance(lic.get("features"), dict) else DEFAULT_LICENSE_FEATURES.copy()
    return {
        "license": lic,
        "license_status": status,
        "license_features": features,
        "license_is_demo": status == "demo",
        "license_is_dev": status in {"dev", "developer"},
        "license_label": lic.get("edition", "Demo"),
        "license_provider": lic.get("provider"),
        "license_remote_status": lic.get("status", status),
        "license_message": lic.get("message", ""),
        "customer_logo_url": get_customer_logo_url() if CUSTOMER_LOGO_PATH.exists() else "",
        "license_purchase_url": "",
    }


def has_license_feature(feature_name: str) -> bool:
    ctx = get_license_context(prefer_online=False)
    features = ctx.get("license_features", {}) if isinstance(ctx.get("license_features"), dict) else {}
    if features.get("*") is True:
        return True

    if bool(features.get(feature_name)):
        return True

    # fallback: licenze a pagamento abilitano alcune feature premium anche senza flag esplicito
    if feature_name in {"backup_restore", "print", "charts", "drilldown", "plugins"}:
        status = str(ctx.get("license_status", "")).strip().lower()
        return status not in {"", "demo", "free", "community", "trial"}

    return False


def has_plugin_license_access(plugin_id: str) -> bool:
    pid = str(plugin_id or "").strip().lower()
    if has_license_feature("plugins"):
        return True
    ctx = get_license_context(prefer_online=False)
    if bool(ctx.get("license_is_dev")) or is_dev_runtime():
        return True
    if not pid:
        return False
    candidates = [pid, f"plugin_{pid}", f"plugins.{pid}", f"plugins:{pid}"]
    return any(has_license_feature(name) for name in candidates)


def is_free_license() -> bool:
    ctx = get_license_context(prefer_online=False)
    status = str(ctx.get("license_status", "")).strip().lower()
    return status in {"free"}


def license_allows_lan_access(status: str) -> bool:
    value = str(status or "").strip().lower()
    return value not in {"", "demo", "trial", "free", "community"}


def resolve_public_lan_host() -> str:
    try:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip:
                return ip
    except Exception:
        pass
    return "127.0.0.1"


def get_customer_logo_url() -> str:
    if CUSTOMER_LOGO_PATH.exists():
        try:
            version = int(CUSTOMER_LOGO_PATH.stat().st_mtime)
        except Exception:
            version = int(time.time())
        return f"/branding/customer-logo?v={version}"
    return "/static/img/pivotdesk-logo.png"


def get_customer_logo_meta() -> dict[str, Any]:
    data = read_json(CUSTOMER_LOGO_META_PATH, {})
    return data if isinstance(data, dict) else {}


def can_connect_to_host_port(host: str, port: int, timeout: float = 0.8) -> bool:
    try:
        import socket

        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except Exception:
        return False


def detect_process_bind_host_for_port(port: int) -> str:
    system_name = platform.system().lower()
    pid = str(os.getpid())
    port_text = f":{int(port)}"

    try:
        if system_name == "windows":
            proc = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True,
                text=True,
                check=False,
            )
            rows = (proc.stdout or "").splitlines()
            for row in rows:
                text = " ".join(row.split())
                if not text.lower().startswith("tcp "):
                    continue
                parts = text.split(" ")
                if len(parts) < 5:
                    continue
                local_addr = parts[1]
                state = parts[3].upper()
                row_pid = parts[4]
                if state != "LISTENING" or row_pid != pid:
                    continue
                if port_text not in local_addr:
                    continue
                if local_addr.startswith("["):
                    host = local_addr.split("]:", 1)[0].lstrip("[")
                else:
                    host = local_addr.rsplit(":", 1)[0]
                return host.strip()
    except Exception:
        return ""
    return ""


def maybe_force_lan_rebind_on_startup() -> None:
    # Evita loop in caso di rilancio automatico.
    if os.environ.get("PIVOTDESK_AUTO_REBOUND", "") == "1":
        return
    if os.environ.get("PIVOTDESK_DISABLE_AUTO_LAN_REBIND", "") in {"1", "true", "True"}:
        return

    try:
        ctx = get_license_context(prefer_online=False)
        status = str(ctx.get("license_status", "demo")).strip().lower() or "demo"
        if not license_allows_lan_access(status):
            return

        cfg = load_config()
        port = int(cfg.get("port", 8091))
        detected_host = detect_process_bind_host_for_port(port)
        if detected_host in {"", "0.0.0.0", "::"}:
            return

        low_host = str(detected_host).strip().lower()
        if low_host not in {"127.0.0.1", "::1", "localhost"}:
            return

        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "app:app",
            "--host",
            "0.0.0.0",
            "--port",
            str(port),
        ]
        child_env = os.environ.copy()
        child_env["PIVOTDESK_AUTO_REBOUND"] = "1"
        child_env["PIVOTDESK_RUNTIME_BIND_HOST"] = "0.0.0.0"
        child_env["PIVOTDESK_RUNTIME_BIND_PORT"] = str(port)
        subprocess.Popen(cmd, cwd=str(BASE_DIR), env=child_env)
        time.sleep(0.6)
        os._exit(0)
    except Exception:
        return


def resolve_lan_bind_info(configured_host: str, configured_port: int, lan_by_license: bool) -> tuple[str, int, str]:
    runtime_host = str(os.environ.get("PIVOTDESK_RUNTIME_BIND_HOST", "") or "").strip()
    runtime_port_raw = str(os.environ.get("PIVOTDESK_RUNTIME_BIND_PORT", "") or "").strip()
    runtime_port = configured_port
    if runtime_port_raw:
        try:
            runtime_port = int(runtime_port_raw)
        except Exception:
            runtime_port = configured_port

    if runtime_host:
        return runtime_host, runtime_port, "runtime"

    detected_host = detect_process_bind_host_for_port(configured_port)
    if detected_host:
        return detected_host, configured_port, "socket"

    if not lan_by_license:
        return "127.0.0.1", configured_port, "inferred"
    if configured_host in {"127.0.0.1", "localhost", "::1"}:
        return "0.0.0.0", configured_port, "inferred"
    return configured_host, configured_port, "inferred"


def cleanup_lan_probes(max_age_seconds: int = 600) -> None:
    now = datetime.utcnow().timestamp()
    expired: list[str] = []
    for probe_id, data in LAN_PROBES.items():
        created_ts = float(data.get("created_ts", now))
        if (now - created_ts) > max_age_seconds:
            expired.append(probe_id)
    for probe_id in expired:
        LAN_PROBES.pop(probe_id, None)


def create_dev_license_file() -> dict[str, Any]:
    data = build_dev_license()
    write_json(DEV_LICENSE_PATH, data)
    return data


def slugify(value: str) -> str:
    text = str(value or "").strip().lower()
    out: list[str] = []
    prev_sep = False

    for ch in text:
        if ch.isalnum():
            out.append(ch)
            prev_sep = False
        elif ch in {" ", "-", "_", "."}:
            if not prev_sep:
                out.append("_")
            prev_sep = True

    result = "".join(out).strip("_")
    return result or "item"


def normalize_source_id(value: str | None) -> str:
    return slugify(value or "")


def sanitize_filename(value: str | None) -> str:
    name = str(value or "").strip()
    name = name.replace("\\", "/").split("/")[-1]
    name = "".join(c if (c.isalnum() or c in "._-") else "_" for c in name)

    while "__" in name:
        name = name.replace("__", "_")

    name = name.strip("._-")
    if not name:
        name = "nuova_pivot"

    if not name.lower().endswith(".json"):
        name += ".json"

    return name


def source_folder(source_id: str | None) -> Path:
    sid = normalize_source_id(source_id)
    folder = PIVOTS_DIR / sid
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def looks_like_date_field(field_name: str | None) -> bool:
    f = str(field_name or "").strip().upper()
    if not f:
        return False

    return (
        f == "DATA"
        or f == "DATE"
        or f.startswith("DATA")
        or f.endswith("_DATA")
        or "_DATA_" in f
        or f.endswith("_DT")
        or f.startswith("DT_")
        or f in {"DATA_FC", "DATA_REGISTRAZIONE", "DATA_PAGAMENTO", "DATA_INCASSO"}
    )


def parse_date_series(series: pd.Series) -> pd.Series:
    s = series.fillna("").astype(str).str.strip()
    s = s.replace("", pd.NA)

    dt = pd.to_datetime(s, errors="coerce", dayfirst=True)

    missing = dt.isna() & s.notna()
    if missing.any():
        dt2 = pd.to_datetime(s[missing], errors="coerce", dayfirst=False)
        dt.loc[missing] = dt2

    return dt


def format_filter_date_values(series: pd.Series) -> list[str]:
    dt = parse_date_series(series).dropna()
    if dt.empty:
        return []
    return sorted(dt.dt.strftime("%Y-%m-%d").drop_duplicates().tolist())


def normalize_text_values(series: pd.Series) -> list[str]:
    return (
        series.fillna("")
        .astype(str)
        .map(str.strip)
        .replace("", pd.NA)
        .dropna()
        .drop_duplicates()
        .sort_values(kind="stable")
        .tolist()
    )


def normalize_numeric_values(series: pd.Series) -> list[str] | None:
    raw = series.fillna("").astype(str).map(str.strip).replace("", pd.NA).dropna()
    if raw.empty:
        return []
    numeric = pd.to_numeric(raw, errors="coerce")
    non_null = int(raw.notna().sum())
    numeric_count = int(numeric.notna().sum())
    if non_null <= 0:
        return []
    # Treat as numeric only when most values can be parsed as numbers.
    if (numeric_count / non_null) < 0.8:
        return None
    unique_sorted = sorted(set(float(x) for x in numeric.dropna().tolist()))
    out: list[str] = []
    for val in unique_sorted:
        out.append(str(int(val)) if float(val).is_integer() else format(val, "g"))
    return out


def normalize_source_item(item: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None

    raw_id = (
        item.get("id")
        or item.get("name")
        or item.get("key")
        or item.get("source_id")
        or item.get("title")
        or item.get("label")
    )

    src_id = normalize_source_id(raw_id)
    title = (
        str(item.get("title", "")).strip()
        or str(item.get("label", "")).strip()
        or str(item.get("name", "")).strip()
        or src_id
    )
    src_type = (
        str(item.get("type", "")).strip().lower()
        or str(item.get("kind", "")).strip().lower()
        or "csv"
    )
    if src_type in {"excel", "xls", "xlsm"}:
        src_type = "xlsx"

    if not src_id:
        return None

    normalized: dict[str, Any] = {
        "id": src_id,
        "title": title,
        "type": src_type,
    }

    raw_path = (
        item.get("path")
        or item.get("file")
        or item.get("filepath")
        or item.get("filename")
        or ""
    )
    if raw_path:
        normalized["path"] = str(raw_path).strip()

    config = item.get("config")
    if isinstance(config, dict):
        normalized["config"] = dict(config)
    else:
        normalized["config"] = {}

    if normalized.get("path") and "path" not in normalized["config"]:
        normalized["config"]["path"] = normalized["path"]

    for key in [
        "sheet_name",
        "sheet",
        "table",
        "query",
        "connection_id",
        "spreadsheet_id",
        "worksheet",
        "range",
        "host",
        "port",
        "database",
        "user",
        "password",
        "delimiter",
        "encoding",
        "skip_rows",
    ]:
        if key in item and key not in normalized["config"]:
            normalized["config"][key] = item.get(key)

    for key in ["delimiter", "encoding", "sheet_name", "skip_rows"]:
        if key in item:
            normalized[key] = item.get(key)
        elif key in normalized["config"]:
            normalized[key] = normalized["config"].get(key)

    calculated_fields = get_source_calculated_fields(item)
    if calculated_fields:
        normalized["calculated_fields"] = calculated_fields
        normalized["config"]["calculated_fields"] = calculated_fields
    else:
        normalized.pop("calculated_fields", None)
        normalized["config"].pop("calculated_fields", None)

    if bool(item.get("migration_placeholder")):
        normalized["migration_placeholder"] = True
    migration_note = str(item.get("migration_note", "")).strip()
    if migration_note:
        normalized["migration_note"] = migration_note

    return normalized


def infer_sources_from_pivots_dirs() -> list[dict[str, Any]]:
    inferred_by_id: dict[str, dict[str, Any]] = {}

    if not PIVOTS_DIR.exists():
        return []

    for folder in PIVOTS_DIR.iterdir():
        if not folder.is_dir():
            continue

        fallback_sid = normalize_source_id(folder.name)
        if not fallback_sid:
            continue

        source_payload_files = [
            folder / "source.json",
            folder / "_source.json",
            folder / "source_config.json",
        ]
        for source_payload_file in source_payload_files:
            if not source_payload_file.exists():
                continue
            payload = read_json(source_payload_file, {}) or {}
            candidate = payload.get("source", payload) if isinstance(payload, dict) else {}
            normalized = normalize_source_item(candidate if isinstance(candidate, dict) else {})
            if normalized and normalized.get("id"):
                inferred_by_id[normalized["id"]] = normalized
                break

        for preset_file in folder.glob("*.json"):
            payload = read_json(preset_file, {}) or {}
            if not isinstance(payload, dict):
                continue

            embedded_source = payload.get("source")
            if isinstance(embedded_source, dict):
                normalized_embedded = normalize_source_item(embedded_source)
                if normalized_embedded and normalized_embedded.get("id"):
                    inferred_by_id[normalized_embedded["id"]] = normalized_embedded
                    continue

            sid = normalize_source_id(payload.get("source_id", fallback_sid) or fallback_sid)
            if not sid:
                continue

            current = inferred_by_id.get(sid, {})
            inferred_config = dict(current.get("config", {}) or {})
            payload_source_config = payload.get("source_config")
            if isinstance(payload_source_config, dict):
                inferred_config.update(payload_source_config)

            sheet_hint = (
                payload.get("source_sheet_name")
                or payload.get("source_sheet")
                or inferred_config.get("sheet_name")
                or inferred_config.get("sheet")
                or ""
            )
            skip_rows_hint = (
                payload.get("source_skip_rows")
                if payload.get("source_skip_rows") is not None
                else payload.get("skip_rows")
            )
            if skip_rows_hint is None:
                skip_rows_hint = inferred_config.get("skip_rows")

            title = (
                str(payload.get("source_title", "")).strip()
                or str(payload.get("source_name", "")).strip()
                or str(current.get("title", "")).strip()
                or sid
            )
            source_type_hint = (
                str(payload.get("source_type", "")).strip().lower()
                or str(current.get("type", "")).strip().lower()
                or "csv"
            )
            path_hint = str(payload.get("source_path", "")).strip()
            if path_hint and "path" not in inferred_config:
                inferred_config["path"] = path_hint
            if sheet_hint:
                inferred_config["sheet_name"] = sheet_hint
            if skip_rows_hint is not None and str(skip_rows_hint).strip() != "":
                inferred_config["skip_rows"] = skip_rows_hint

            inferred_item = normalize_source_item(
                {
                    "id": sid,
                    "title": title,
                    "type": source_type_hint,
                    "path": path_hint or current.get("path", ""),
                    "config": inferred_config,
                    "sheet_name": inferred_config.get("sheet_name"),
                    "skip_rows": inferred_config.get("skip_rows"),
                    "migration_placeholder": not bool(path_hint or current.get("path")),
                    "migration_note": "Sorgente inferita dai preset migrati. Verifica percorso/tipo prima dell'uso.",
                }
            )
            if inferred_item:
                inferred_by_id[sid] = inferred_item

    return list(inferred_by_id.values())


def remap_pivot_source_ids(id_map: dict[str, str]) -> bool:
    """
    Aggiorna cartelle preset e payload JSON quando gli id sorgente vengono
    migrati (es. legacy string -> id numerico).
    """
    normalized_map: dict[str, str] = {}
    for old_raw, new_raw in (id_map or {}).items():
        old_id = normalize_source_id(old_raw)
        new_id = normalize_source_id(new_raw)
        if old_id and new_id and old_id != new_id:
            normalized_map[old_id] = new_id

    if not normalized_map:
        return False

    changed = False

    for old_id, new_id in normalized_map.items():
        old_folder = PIVOTS_DIR / old_id
        new_folder = PIVOTS_DIR / new_id
        if old_folder.exists() and old_folder.is_dir():
            new_folder.parent.mkdir(parents=True, exist_ok=True)
            if not new_folder.exists():
                old_folder.rename(new_folder)
                changed = True
            else:
                for payload_file in old_folder.glob("*.json"):
                    target_file = new_folder / payload_file.name
                    if target_file.exists():
                        continue
                    payload_file.rename(target_file)
                    changed = True
                try:
                    old_folder.rmdir()
                except OSError:
                    pass

    for folder in PIVOTS_DIR.glob("*"):
        if not folder.is_dir():
            continue
        for payload_file in folder.glob("*.json"):
            payload = read_json(payload_file, {})
            if not isinstance(payload, dict):
                continue
            file_changed = False
            current_sid = normalize_source_id(payload.get("source_id"))
            if current_sid in normalized_map:
                payload["source_id"] = normalized_map[current_sid]
                file_changed = True
            embedded = payload.get("source")
            if isinstance(embedded, dict):
                embedded_sid = normalize_source_id(embedded.get("id"))
                if embedded_sid in normalized_map:
                    embedded["id"] = normalized_map[embedded_sid]
                    file_changed = True
            if file_changed:
                write_json(payload_file, payload)
                changed = True

    return changed


def _infer_source_type_from_path(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".xlsx", ".xlsm", ".xls"}:
        return "xlsx"
    if ext == ".ods":
        return "ods"
    return "csv"


def _detect_columns_for_import_path(path: Path, source_type: str) -> list[str]:
    try:
        if source_type == "csv":
            df, _, _ = _read_csv_local(str(path), delimiter=",", encoding="utf-8-sig", skip_rows=0)
            return [str(c).strip() for c in list(df.columns) if str(c).strip()]
        if source_type in {"xlsx", "ods"}:
            df = pd.read_excel(str(path), nrows=0)
            return [str(c).strip() for c in list(df.columns) if str(c).strip()]
    except Exception:
        return []
    return []


def _auto_import_data_sources(items: list[dict[str, Any]], used_numeric: set[int]) -> tuple[list[dict[str, Any]], bool]:
    IMPORT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    files = [p for p in IMPORT_DATA_DIR.iterdir() if p.is_file() and p.suffix.lower() in {".csv", ".xlsx", ".xlsm", ".xls", ".ods"}]
    if not files:
        return items, False
    by_path = {str(Path(str(row.get("path", ""))).resolve()): row for row in items}
    changed = False
    out = list(items)
    for f in sorted(files):
        f_resolved = str(f.resolve())
        stype = _infer_source_type_from_path(f)
        title = f"Import {f.stem}"
        columns = _detect_columns_for_import_path(f, stype)
        existing = by_path.get(f_resolved)
        if existing:
            cfg = dict(existing.get("config") if isinstance(existing.get("config"), dict) else {})
            if columns:
                cfg["detected_columns"] = columns
            cfg["auto_import_data"] = True
            existing["config"] = cfg
            existing["type"] = stype
            changed = True
            continue
        next_n = (max(used_numeric) + 1) if used_numeric else 1
        while next_n in used_numeric:
            next_n += 1
        used_numeric.add(next_n)
        new_item = normalize_source_item({
            "id": str(next_n),
            "title": title,
            "type": stype,
            "path": str(f),
            "delimiter": ",",
            "encoding": "utf-8-sig",
            "config": {"auto_import_data": True, "detected_columns": columns},
        })
        if new_item:
            out.append(new_item)
            changed = True
    return out, changed


def load_sources_data() -> dict[str, Any]:
    raw = read_json(SOURCES_PATH, DEFAULT_SOURCES.copy()) or {}

    raw_items = raw.get("items")
    if raw_items is None:
        raw_items = raw.get("sources", [])
    items = raw_items or []

    normalized_items: list[dict[str, Any]] = []

    for item in items:
        normalized = normalize_source_item(item)
        if normalized:
            normalized_items.append(normalized)

    default_source = normalize_source_id(raw.get("default_source", ""))

    if not normalized_items and LEGACY_SOURCES_PATH.exists():
        legacy_raw = read_json(LEGACY_SOURCES_PATH, {}) or {}
        legacy_items = legacy_raw.get("items")
        if legacy_items is None:
            legacy_items = legacy_raw.get("sources", [])
        for item in legacy_items or []:
            normalized = normalize_source_item(item)
            if normalized:
                normalized_items.append(normalized)

        legacy_default = normalize_source_id(legacy_raw.get("default_source", ""))
        if legacy_default:
            default_source = legacy_default

        if normalized_items:
            seeded = {
                "default_source": default_source or normalized_items[0]["id"],
                "items": normalized_items,
            }
            write_json(SOURCES_PATH, seeded)
            return seeded

    changed_ids = False
    id_remap: dict[str, str] = {}
    used_numeric: set[int] = set()
    remapped_items: list[dict[str, Any]] = []
    for item in normalized_items:
        old_id = str(item.get("id", "")).strip()
        digits = re.sub(r"[^0-9]+", "", old_id)
        target = ""
        if digits:
            try:
                n = int(digits)
                if n > 0 and n not in used_numeric:
                    target = str(n)
                    used_numeric.add(n)
            except Exception:
                target = ""
        if not target:
            next_n = (max(used_numeric) + 1) if used_numeric else 1
            while next_n in used_numeric:
                next_n += 1
            used_numeric.add(next_n)
            target = str(next_n)
        new_item = dict(item)
        if target != old_id:
            changed_ids = True
            id_remap[old_id] = target
            cfg = dict(new_item.get("config") if isinstance(new_item.get("config"), dict) else {})
            if old_id:
                cfg["legacy_source_id"] = old_id
            new_item["config"] = cfg
        new_item["id"] = target
        remapped_items.append(new_item)
    normalized_items = remapped_items

    if default_source:
        remapped_default = next(
            (
                x["id"]
                for x in normalized_items
                if x["id"] == default_source or str((x.get("config") or {}).get("legacy_source_id", "")) == default_source
            ),
            "",
        )
        if remapped_default and remapped_default != default_source:
            changed_ids = True
            default_source = remapped_default

    if not default_source and normalized_items:
        default_source = normalized_items[0]["id"]

    if default_source and not any(x["id"] == default_source for x in normalized_items):
        default_source = normalized_items[0]["id"] if normalized_items else ""

    known_source_ids = {x["id"] for x in normalized_items}
    inferred_items = infer_sources_from_pivots_dirs()
    inferred_added = False
    for item in inferred_items:
        sid = item.get("id")
        if not sid or sid in known_source_ids:
            continue
        known_source_ids.add(sid)
        normalized_items.append(item)
        inferred_added = True

    normalized_items, import_data_added = _auto_import_data_sources(normalized_items, used_numeric)

    if not default_source and normalized_items:
        default_source = normalized_items[0]["id"]

    merged = {
        "default_source": default_source,
        "items": normalized_items,
    }

    pivots_remapped = remap_pivot_source_ids(id_remap) if changed_ids else False

    if inferred_added or changed_ids or pivots_remapped or import_data_added:
        write_json(SOURCES_PATH, merged)

    return merged


def save_sources_data(data: dict[str, Any]) -> dict[str, Any]:
    raw_items = data.get("items", []) or []
    normalized_items: list[dict[str, Any]] = []

    for item in raw_items:
        normalized = normalize_source_item(item)
        if normalized:
            normalized_items.append(normalized)

    default_source = normalize_source_id(data.get("default_source", ""))
    if not default_source and normalized_items:
        default_source = normalized_items[0]["id"]

    if default_source and not any(x["id"] == default_source for x in normalized_items):
        default_source = normalized_items[0]["id"] if normalized_items else ""

    clean_data = {
        "default_source": default_source,
        "items": normalized_items,
    }

    write_json(SOURCES_PATH, clean_data)
    return clean_data


def get_source_by_id(source_id: str | None) -> dict[str, Any] | None:
    sid = normalize_source_id(source_id)
    data = load_sources_data()
    found = next((x for x in data.get("items", []) if x["id"] == sid), None)
    if found:
        return found
    return next(
        (
            x
            for x in data.get("items", [])
            if str((x.get("config") or {}).get("legacy_source_id", "")).strip() == sid
        ),
        None,
    )


def load_source_df(source_id: str | None) -> tuple[dict[str, Any], pd.DataFrame]:
    src = get_source_by_id(source_id)
    if not src:
        raise FileNotFoundError(f"Sorgente non trovata: {source_id}")
    source_path = str(src.get("path") or src.get("config", {}).get("path") or "").strip()
    source_type = str(src.get("type", "")).strip().lower()
    if not source_path and source_type not in {"mysql", "gsheet_account"}:
        raise FileNotFoundError(
            "La sorgente selezionata non ha ancora un percorso configurato. "
            "Apri 'Gestione sorgenti' e completa i parametri della sorgente migrata."
        )
    if is_free_license():
        if source_type != "csv":
            raise PermissionError("Licenza Free: sono consentite solo sorgenti CSV per la pivot a video.")

    return src, load_dataframe_with_source_calculated_fields(src, use_fallback=True)


def load_dataframe_with_source_calculated_fields(
    source: dict[str, Any],
    *,
    use_fallback: bool = False,
) -> pd.DataFrame:
    source_calculated_fields = get_source_calculated_fields(source)
    cache_key = _source_cache_key(source, source_calculated_fields)
    now_ts = time.time()

    _source_cache_cleanup(now_ts)
    cached = _SOURCE_DATAFRAME_CACHE.get(cache_key)
    if cached and (now_ts - float(cached.get("ts", 0.0))) <= SOURCE_DATAFRAME_CACHE_TTL_SEC:
        _SOURCE_DATAFRAME_CACHE.move_to_end(cache_key, last=True)
        return cached["df"].copy()

    df = load_dataframe_from_source_with_fallback(source) if use_fallback else load_dataframe_from_source(source)

    if df is None:
        raise RuntimeError(
            f"Nessun dataframe restituito dal connector per la sorgente: {source.get('id', '(senza id)')}"
        )

    if not isinstance(df, pd.DataFrame):
        raise RuntimeError(
            f"Il connector non ha restituito un DataFrame valido per: {source.get('id', '(senza id)')}"
        )

    out_df = df.copy()
    out_df.columns = [str(c).strip() for c in out_df.columns]
    out_df = out_df.fillna("")
    source_aliases = get_source_column_aliases(source)
    out_df = apply_column_aliases_to_dataframe(out_df, source_aliases)
    out_df = apply_calculated_fields_to_dataframe(out_df, source_calculated_fields)

    size_mb = _estimate_dataframe_size_mb(out_df)
    if size_mb <= float(SOURCE_DATAFRAME_CACHE_MAX_ENTRY_MB):
        _SOURCE_DATAFRAME_CACHE[cache_key] = {
            "ts": now_ts,
            "source_id": normalize_source_id(source.get("id")),
            "size_mb": size_mb,
            "df": out_df.copy(),
        }
        _SOURCE_DATAFRAME_CACHE.move_to_end(cache_key, last=True)
        _source_cache_cleanup(now_ts)

    return out_df


def load_dataframe_for_plugin(source: dict[str, Any]) -> pd.DataFrame:
    if is_free_license():
        source_type = str(source.get("type", "")).strip().lower()
        if source_type != "csv":
            raise PermissionError("Licenza Free: i plugin dati remoti sono disponibili solo nelle versioni a pagamento.")
    return load_dataframe_with_source_calculated_fields(source, use_fallback=False)


def get_runtime_paths() -> dict[str, str]:
    return {
        "base_dir": str(BASE_DIR),
        "static_dir": str(STATIC_DIR),
        "templates_dir": str(TEMPLATES_DIR),
        "data_dir": str(DATA_DIR),
        "pivots_dir": str(PIVOTS_DIR),
        "config_path": str(CONFIG_PATH),
        "settings_path": str(SETTINGS_PATH),
        "sources_path": str(SOURCES_PATH),
    }


def get_plugin_roots() -> list[Path]:
    roots = [
        BASE_DIR / "plugins",
        APP_HOME_DIR / "plugins",
        resource_path("plugins"),
    ]
    out: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.resolve()) if root.exists() else str(root)
        if key in seen:
            continue
        seen.add(key)
        out.append(root)
    return out


def load_plugins_enabled_map() -> dict[str, bool]:
    raw = read_json(PLUGINS_CONFIG_PATH, None)
    if not isinstance(raw, dict) and LEGACY_PLUGINS_CONFIG_PATH.exists():
        raw = read_json(LEGACY_PLUGINS_CONFIG_PATH, {}) or {}
    if not isinstance(raw, dict):
        raw = {}
    enabled = raw.get("enabled", {}) if isinstance(raw, dict) else {}
    if not isinstance(enabled, dict):
        enabled = {}

    normalized = {str(k): bool(v) for k, v in enabled.items()}

    # In developer runtime, default-enable all discovered plugins unless
    # explicitly disabled in plugins.json.
    if is_dev_runtime():
        for plugins_root in get_plugin_roots():
            if not plugins_root.exists():
                continue
            for plugin_dir in plugins_root.iterdir():
                if not plugin_dir.is_dir():
                    continue
                manifest = read_json(plugin_dir / "manifest.json", {}) or {}
                plugin_id = str(manifest.get("id") or plugin_dir.name).strip()
                if plugin_id and plugin_id not in normalized:
                    normalized[plugin_id] = True

    return normalized


def save_plugins_enabled_map(enabled_map: dict[str, bool]) -> dict[str, bool]:
    clean = {str(k): bool(v) for k, v in (enabled_map or {}).items() if str(k).strip()}
    write_json(PLUGINS_CONFIG_PATH, {"enabled": clean})
    return clean


def sanitize_values(values: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    for item in values or []:
        field = str(item.get("field", "")).strip()
        agg = str(item.get("agg", "sum")).strip().lower() or "sum"
        label = str(item.get("label", "")).strip() or field

        if not field:
            continue

        out.append({"field": field, "agg": agg, "label": label})

    return out


def sanitize_calculated_fields(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in items or []:
        if not isinstance(item, dict):
            continue

        name = str(item.get("name", "")).strip()
        formula = str(item.get("formula", "")).strip()
        field_type = str(item.get("type", "string")).strip().lower() or "string"
        enabled = bool(item.get("enabled", True))

        if not name or not formula:
            continue
        if field_type not in {"string", "number", "date", "boolean"}:
            field_type = "string"
        if name in seen:
            continue

        seen.add(name)
        out.append(
            {
                "name": name,
                "formula": formula,
                "type": field_type,
                "enabled": enabled,
            }
        )

    return out


def get_source_calculated_fields(source: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(source, dict):
        return []
    config = source.get("config") if isinstance(source.get("config"), dict) else {}
    from_source = source.get("calculated_fields", [])
    from_config = config.get("calculated_fields", [])

    source_fields = sanitize_calculated_fields(from_source if isinstance(from_source, list) else [])
    if source_fields:
        return source_fields
    return sanitize_calculated_fields(from_config if isinstance(from_config, list) else [])


def sanitize_column_aliases(raw: Any) -> dict[str, str]:
    if isinstance(raw, list):
        out: dict[str, str] = {}
        for row in raw:
            if not isinstance(row, dict):
                continue
            src = str(row.get("source") or row.get("from") or "").strip()
            alias = str(row.get("alias") or row.get("to") or "").strip()
            if src and alias:
                out[src] = alias
        return out
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for src, alias in raw.items():
        left = str(src or "").strip()
        right = str(alias or "").strip()
        if left and right:
            out[left] = right
    return out


def get_source_column_aliases(source: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(source, dict):
        return {}
    config = source.get("config") if isinstance(source.get("config"), dict) else {}
    from_source = sanitize_column_aliases(source.get("column_aliases"))
    if from_source:
        return from_source
    return sanitize_column_aliases(config.get("column_aliases"))


def apply_column_aliases_to_dataframe(df: pd.DataFrame, aliases: dict[str, str]) -> pd.DataFrame:
    if not aliases:
        return df
    rename_map = {}
    for src, alias in aliases.items():
        if src in df.columns:
            rename_map[src] = alias
    if not rename_map:
        return df
    return df.rename(columns=rename_map)


def apply_calculated_fields_to_dataframe(
    df: pd.DataFrame,
    calculated_fields: list[dict[str, Any]] | None,
) -> pd.DataFrame:
    definitions = build_calculated_definitions(calculated_fields)
    if not definitions:
        return df

    base_columns = [str(c).strip() for c in df.columns]
    rows = df.to_dict(orient="records")
    new_rows = apply_calculated_fields(rows, definitions)
    if not new_rows:
        return df

    out = pd.DataFrame(new_rows)
    calculated_names = [d.name for d in definitions if getattr(d, "name", "").strip()]
    desired_order = base_columns + [name for name in calculated_names if name not in base_columns]
    existing_order = [c for c in desired_order if c in out.columns]
    remaining = [c for c in out.columns if c not in existing_order]
    if existing_order or remaining:
        out = out[existing_order + remaining]

    return out


def _source_cache_invalidation_fingerprint(source: dict[str, Any]) -> str:
    cfg = source.get("config") if isinstance(source.get("config"), dict) else {}
    source_type = str(source.get("type", "")).strip().lower()
    source_path = str(source.get("path") or cfg.get("path") or "").strip()

    if source_type in {"csv", "xlsx", "excel", "ods"} and source_path:
        try:
            stat = Path(source_path).expanduser().stat()
            return f"{stat.st_mtime_ns}:{stat.st_size}"
        except Exception:
            return "missing"
    return "remote"


def _source_cache_key(source: dict[str, Any], source_calculated_fields: list[dict[str, Any]]) -> str:
    cfg = source.get("config") if isinstance(source.get("config"), dict) else {}
    payload = {
        "id": str(source.get("id", "")).strip(),
        "type": str(source.get("type", "")).strip().lower(),
        "path": str(source.get("path") or cfg.get("path") or "").strip(),
        "sheet_name": str(source.get("sheet_name") or cfg.get("sheet_name") or cfg.get("sheet") or "").strip(),
        "delimiter": str(source.get("delimiter") or cfg.get("delimiter") or "").strip(),
        "encoding": str(source.get("encoding") or cfg.get("encoding") or "").strip(),
        "skip_rows": int(source.get("skip_rows", cfg.get("skip_rows", 0)) or 0),
        "query": str(cfg.get("query") or "").strip(),
        "table": str(cfg.get("table") or "").strip(),
        "connection_id": str(cfg.get("connection_id") or "").strip(),
        "calc": source_calculated_fields,
        "column_aliases": get_source_column_aliases(source),
        "stamp": _source_cache_invalidation_fingerprint(source),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _estimate_dataframe_size_mb(df: pd.DataFrame) -> float:
    try:
        size_bytes = float(df.memory_usage(index=True, deep=True).sum())
    except Exception:
        size_bytes = 0.0
    return size_bytes / (1024.0 * 1024.0)


def _source_cache_cleanup(now_ts: float) -> None:
    expired = [
        key
        for key, value in _SOURCE_DATAFRAME_CACHE.items()
        if (now_ts - float(value.get("ts", 0.0))) > SOURCE_DATAFRAME_CACHE_TTL_SEC
    ]
    for key in expired:
        _SOURCE_DATAFRAME_CACHE.pop(key, None)

    max_total_mb = float(SOURCE_DATAFRAME_CACHE_MAX_TOTAL_MB)
    total_mb = sum(float(item.get("size_mb", 0.0)) for item in _SOURCE_DATAFRAME_CACHE.values())

    while _SOURCE_DATAFRAME_CACHE and (
        len(_SOURCE_DATAFRAME_CACHE) > SOURCE_DATAFRAME_CACHE_MAX_ENTRIES or total_mb > max_total_mb
    ):
        _, removed = _SOURCE_DATAFRAME_CACHE.popitem(last=False)
        total_mb -= float(removed.get("size_mb", 0.0))


def clear_source_dataframe_cache(source_id: str | None = None) -> None:
    if not source_id:
        _SOURCE_DATAFRAME_CACHE.clear()
        return
    sid = normalize_source_id(source_id)
    to_drop = [key for key, value in _SOURCE_DATAFRAME_CACHE.items() if value.get("source_id") == sid]
    for key in to_drop:
        _SOURCE_DATAFRAME_CACHE.pop(key, None)


def normalize_preset_options(raw_options: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw_options or {}

    options = {
        "measures_layout": str(raw.get("measures_layout", "vertical")).strip().lower() or "vertical",
        "show_row_totals": bool(raw.get("show_row_totals", True)),
        "show_col_totals": bool(raw.get("show_col_totals", True)),
        "show_subtotals": bool(raw.get("show_subtotals", False)),
        "sort_enabled": bool(raw.get("sort_enabled", False)),
        "sort_field": str(raw.get("sort_field", "")).strip(),
        "sort_direction": str(raw.get("sort_direction", "asc")).strip().lower() or "asc",
        "sort_by": str(raw.get("sort_by", "label")).strip().lower() or "label",
    }

    if options["measures_layout"] not in {"vertical", "horizontal"}:
        options["measures_layout"] = "vertical"

    if options["sort_direction"] not in {"asc", "desc"}:
        options["sort_direction"] = "asc"

    if options["sort_by"] not in {"label", "value"}:
        options["sort_by"] = "label"

    return options


def build_preset_payload(payload: dict[str, Any]) -> dict[str, Any]:
    source_id = normalize_source_id(payload.get("source_id"))
    filename = sanitize_filename(payload.get("filename"))
    title = str(payload.get("title", "")).strip() or Path(filename).stem

    filters = [str(x).strip() for x in (payload.get("filters", []) or []) if str(x).strip()]
    rows = [str(x).strip() for x in (payload.get("rows", []) or []) if str(x).strip()]
    cols = [str(x).strip() for x in (payload.get("cols", []) or []) if str(x).strip()]
    numeric_fields = [str(x).strip() for x in (payload.get("numeric_fields", []) or []) if str(x).strip()]
    date_fields = [str(x).strip() for x in (payload.get("date_fields", []) or []) if str(x).strip()]
    values = sanitize_values(payload.get("values", []))
    calculated_fields = sanitize_calculated_fields(payload.get("calculated_fields", []))
    options = normalize_preset_options(payload.get("options", {}))

    return {
        "id": Path(filename).stem,
        "title": title,
        "source_id": source_id,
        "filters": filters,
        "numeric_fields": numeric_fields,
        "date_fields": date_fields,
        "rows": rows,
        "cols": cols,
        "values": values,
        "calculated_fields": calculated_fields,
        "options": options,
    }


def load_pivot_files(source_id: str | None = None) -> list[dict[str, Any]]:
    if str(PIVOTS_DIR.resolve()) != str(LEGACY_PIVOTS_DIR.resolve()):
        runtime_has_pivots = any(PIVOTS_DIR.glob("*/*.json")) if PIVOTS_DIR.exists() else False
        if not runtime_has_pivots and LEGACY_PIVOTS_DIR.exists():
            for legacy_folder in LEGACY_PIVOTS_DIR.iterdir():
                if not legacy_folder.is_dir():
                    continue
                target_folder = PIVOTS_DIR / legacy_folder.name
                target_folder.mkdir(parents=True, exist_ok=True)
                for legacy_file in legacy_folder.glob("*.json"):
                    target_file = target_folder / legacy_file.name
                    if not target_file.exists():
                        try:
                            shutil.copy2(legacy_file, target_file)
                        except Exception:
                            continue

    items: list[dict[str, Any]] = []

    if source_id:
        sid = normalize_source_id(source_id)
        folders = [source_folder(sid)]
    else:
        folders = [p for p in PIVOTS_DIR.iterdir() if p.is_dir()] if PIVOTS_DIR.exists() else []

    for folder in folders:
        sid = normalize_source_id(folder.name)

        for file in sorted(folder.glob("*.json")):
            try:
                data = read_json(file, {}) or {}
                if not data:
                    continue

                data["id"] = str(data.get("id", file.stem)).strip() or file.stem
                data["title"] = str(data.get("title", data["id"])).strip() or data["id"]
                data["source_id"] = normalize_source_id(data.get("source_id", sid) or sid)
                data["filters"] = [str(x).strip() for x in (data.get("filters", []) or []) if str(x).strip()]
                data["numeric_fields"] = [str(x).strip() for x in (data.get("numeric_fields", []) or []) if str(x).strip()]
                data["date_fields"] = [str(x).strip() for x in (data.get("date_fields", []) or []) if str(x).strip()]
                data["rows"] = [str(x).strip() for x in (data.get("rows", []) or []) if str(x).strip()]
                data["cols"] = [str(x).strip() for x in (data.get("cols", []) or []) if str(x).strip()]
                data["values"] = sanitize_values(data.get("values", []))
                data["calculated_fields"] = sanitize_calculated_fields(data.get("calculated_fields", []))
                data["options"] = normalize_preset_options(data.get("options", {}))
                data["_filename"] = file.name

                # importantissimo: non includere preset "sporchi" di altre sorgenti
                if source_id and data["source_id"] != sid:
                    continue

                items.append(data)
            except Exception:
                continue

    return items


def find_existing_preset_file(filename: str, preset_id: str | None = None) -> tuple[str | None, Path | None]:
    if not PIVOTS_DIR.exists():
        return None, None

    normalized_filename = sanitize_filename(filename)
    normalized_preset_id = str(preset_id or "").strip()

    for folder in PIVOTS_DIR.iterdir():
        if not folder.is_dir():
            continue

        sid = normalize_source_id(folder.name)

        candidate = folder / normalized_filename
        if candidate.exists():
            return sid, candidate

        if normalized_preset_id:
            alt_candidate = folder / sanitize_filename(f"{normalized_preset_id}.json")
            if alt_candidate.exists():
                return sid, alt_candidate

        for file in folder.glob("*.json"):
            try:
                data = read_json(file, {}) or {}
                if not data:
                    continue

                file_preset_id = str(data.get("id", file.stem)).strip()
                if normalized_preset_id and file_preset_id == normalized_preset_id:
                    return sid, file
            except Exception:
                continue

    return None, None

def save_preset_file(source_id: str, filename: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    sid = normalize_source_id(source_id)
    fname = sanitize_filename(filename)

    incoming_id = str(payload.get("id", "")).strip() or Path(fname).stem
    existing_sid, existing_path = find_existing_preset_file(fname, incoming_id)

    folder = source_folder(sid)
    new_path = folder / fname

    data = build_preset_payload({**payload, "source_id": sid, "filename": fname})
    write_json(new_path, data)

    if existing_path and existing_path.resolve() != new_path.resolve():
        try:
            existing_path.unlink()
        except Exception:
            pass

    return fname, data


def delete_preset_file(source_id: str, filename: str | None = None, preset_id: str | None = None) -> bool:
    sid = normalize_source_id(source_id)
    folder = source_folder(sid)

    candidates: list[Path] = []

    if filename:
        candidates.append(folder / sanitize_filename(filename))

    if preset_id:
        candidates.append(folder / sanitize_filename(f"{preset_id}.json"))

    seen: set[Path] = set()
    unique_candidates: list[Path] = []

    for candidate in candidates:
        if candidate not in seen:
            unique_candidates.append(candidate)
            seen.add(candidate)

    for path in unique_candidates:
        if path.exists():
            path.unlink()
            return True

    return False


def validate_preset_columns(columns: list[str], preset: dict[str, Any]) -> list[str]:
    available = set(columns)
    required: set[str] = set()

    for key in ["filters", "rows", "cols", "numeric_fields", "date_fields"]:
        for item in preset.get(key, []) or []:
            if item:
                required.add(str(item).strip())

    for value in preset.get("values", []) or []:
        field = str(value.get("field", "")).strip()
        if field:
            required.add(field)

    return sorted(col for col in required if col not in available)


def find_preset_by_id(pivot_id: str, source_id: str | None = None) -> dict[str, Any] | None:
    pid = str(pivot_id or "").strip()
    sid = normalize_source_id(source_id) if source_id else ""
    if not pid:
        return None

    all_pivots = load_pivot_files()
    return next(
        (
            item
            for item in all_pivots
            if item.get("id") == pid and ((not sid) or item.get("source_id") == sid)
        ),
        None,
    )


def apply_preset_calculated_fields(
    df: pd.DataFrame,
    pivot_id: str | None = None,
    source_id: str | None = None,
) -> pd.DataFrame:
    pid = str(pivot_id or "").strip()
    if not pid:
        return df

    preset = find_preset_by_id(pid, source_id=source_id)
    if not preset:
        return df

    return apply_calculated_fields_to_dataframe(df, preset.get("calculated_fields", []))


def build_backup_payload() -> dict[str, Any]:
    presets = load_pivot_files()
    exported_presets: list[dict[str, Any]] = []

    for item in presets:
        source_id = normalize_source_id(item.get("source_id"))
        filename = sanitize_filename(item.get("_filename") or f"{item.get('id', 'preset')}.json")
        preset_payload = dict(item)
        preset_payload.pop("_filename", None)
        exported_presets.append(
            {
                "source_id": source_id,
                "filename": filename,
                "preset": preset_payload,
            }
        )

    return {
        "app": "PivotDesk",
        "version": 1,
        "exported_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "settings": load_settings_data(),
        "presets": exported_presets,
    }


def restore_backup_payload(payload: dict[str, Any], replace_existing: bool = True) -> dict[str, Any]:
    settings = payload.get("settings", {}) if isinstance(payload.get("settings"), dict) else {}
    presets_raw = payload.get("presets", [])
    if not isinstance(presets_raw, list):
        raise ValueError("Formato backup non valido: presets deve essere una lista.")

    saved_settings = save_settings_data(settings)

    if replace_existing and PIVOTS_DIR.exists():
        for folder in PIVOTS_DIR.iterdir():
            if not folder.is_dir():
                continue
            for file in folder.glob("*.json"):
                try:
                    file.unlink()
                except Exception:
                    pass

    restored_count = 0
    skipped_count = 0

    for row in presets_raw:
        if not isinstance(row, dict):
            skipped_count += 1
            continue
        source_id = normalize_source_id(row.get("source_id"))
        filename = sanitize_filename(row.get("filename") or "")
        preset = row.get("preset", {})
        if not source_id or not filename or not isinstance(preset, dict):
            skipped_count += 1
            continue
        try:
            save_preset_file(source_id, filename, {**preset, "source_id": source_id})
            restored_count += 1
        except Exception:
            skipped_count += 1

    return {
        "settings": saved_settings,
        "restored_presets": restored_count,
        "skipped_presets": skipped_count,
    }


def get_user_runtime_root(username: str | None) -> Path:
    uname = normalize_source_id(username or "guest") or "guest"
    root = DATA_DIR / "userspace" / uname
    root.mkdir(parents=True, exist_ok=True)
    (root / "uploads").mkdir(parents=True, exist_ok=True)
    return root


def get_current_username(request: Request) -> str:
    user = get_current_user_from_session(request)
    return str(user.get("username", "guest")) if user else "guest"


def build_dataframe_preview_payload(src: dict[str, Any], df: pd.DataFrame, limit: int = 20) -> dict[str, Any]:
    limit = max(1, min(int(limit), 100))
    columns = [str(c) for c in df.columns]
    cfg = src.get("config", {}) if isinstance(src.get("config"), dict) else {}
    delimiter = src.get("delimiter") or cfg.get("delimiter") or ""
    encoding = src.get("encoding") or cfg.get("encoding") or ""
    sheet_name = src.get("sheet_name") or cfg.get("sheet_name") or cfg.get("sheet") or ""
    skip_rows = src.get("skip_rows")
    if skip_rows is None:
        skip_rows = cfg.get("skip_rows", 0)
    rows = df.fillna("").head(limit).astype(str).to_dict(orient="records")
    source_type = src.get("type", "csv")
    if str(source_type).lower() == "csv":
        resolved_info = f"CSV · delimitatore: {(delimiter.replace(chr(9), 'TAB') if delimiter else 'auto')} · encoding: {encoding or 'auto'}"
    else:
        resolved_info = f"Excel · foglio: {sheet_name or 'primo foglio'}"
    return {
        "source_id": src.get("id"),
        "source_title": src.get("title") or src.get("id"),
        "source_type": source_type,
        "columns": columns,
        "rows": rows,
        "shown_rows": len(rows),
        "total_rows": int(len(df)),
        "total_columns": len(columns),
        "delimiter": delimiter,
        "encoding": encoding,
        "sheet_name": sheet_name,
        "skip_rows": int(skip_rows or 0),
        "resolved_info": resolved_info,
    }


def dataframe_preview_payload(source_id: str, limit: int = 20) -> dict[str, Any]:
    src, df = load_source_df(source_id)
    return build_dataframe_preview_payload(src, df, limit=limit)


def build_source_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    src_type = str(payload.get("type", "csv") or "csv").strip().lower() or "csv"
    if src_type in {"google_drive", "google_sheet"}:
        src_type = "gdrive"
    path = str(payload.get("path", "") or "").strip()
    delimiter = str(payload.get("delimiter", "") or "").strip()
    encoding = str(payload.get("encoding", "") or "").strip()
    sheet_name = str(payload.get("sheet_name", "") or "").strip()
    skip_rows = payload.get("skip_rows", 0)
    try:
        skip_rows = max(int(skip_rows or 0), 0)
    except Exception:
        skip_rows = 0
    cfg_payload = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    source_calculated_fields = sanitize_calculated_fields(
        payload.get("calculated_fields", cfg_payload.get("calculated_fields", []))
    )
    config = {
        "path": path,
        "delimiter": delimiter,
        "encoding": encoding,
        "sheet_name": sheet_name,
        "skip_rows": skip_rows,
    }
    for key in (
        "url",
        "method",
        "json_path",
        "timeout_sec",
        "connection_id",
        "table",
        "query",
        "spreadsheet_id",
        "worksheet",
        "range",
        "column_aliases",
    ):
        if key in cfg_payload and cfg_payload.get(key) not in (None, ""):
            config[key] = cfg_payload.get(key)
    if source_calculated_fields:
        config["calculated_fields"] = source_calculated_fields

    source = {
        "id": normalize_source_id(payload.get("id") or "preview") or "preview",
        "title": str(payload.get("title") or payload.get("id") or "Anteprima sorgente").strip() or "Anteprima sorgente",
        "type": src_type,
        "path": path,
        "delimiter": delimiter,
        "encoding": encoding,
        "sheet_name": sheet_name,
        "skip_rows": skip_rows,
        "config": config,
    }
    if source_calculated_fields:
        source["calculated_fields"] = source_calculated_fields
    return normalize_source_item(source) or source


def list_excel_sheet_names(path: str) -> list[str]:
    with pd.ExcelFile(path) as workbook:
        return [str(name) for name in (workbook.sheet_names or [])]


def plugin_compute_pivot_result(
    *,
    pivot_id: str,
    source_id: str | None = None,
    filters: str | None = None,
    view_options: str | None = None,
) -> dict[str, Any]:
    return _compute_pivot_result(
        pivot_id=pivot_id,
        source_id=source_id,
        filters=filters,
        view_options=view_options,
    )


def _merge_json_safe(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    try:
        if value != value:  # NaN
            return ""
    except Exception:
        pass
    return str(value)


def _load_merge_template_record(template_id: str) -> dict[str, Any] | None:
    wanted = str(template_id or "").strip()
    if not wanted:
        return None
    db_path = DATA_DIR / "app_data" / "merge_templates.db"
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            row = conn.execute(
                "SELECT template_id,title,columns_json,sources_json,include_source_tag FROM merge_templates WHERE template_id = ?",
                (wanted,),
            ).fetchone()
            conn.close()
            if row:
                columns = json.loads(row[2]) if str(row[2] or "").strip() else []
                sources = json.loads(row[3]) if str(row[3] or "").strip() else []
                return {
                    "template_id": str(row[0] or "").strip(),
                    "title": str(row[1] or "").strip(),
                    "columns": columns if isinstance(columns, list) else [],
                    "sources": sources if isinstance(sources, list) else [],
                    "include_source_tag": bool(row[4]),
                }
        except Exception:
            pass

    legacy = DATA_DIR / "merge_templates.json"
    if legacy.exists():
        try:
            raw = read_json(legacy, {}) or {}
            for item in (raw.get("templates", []) if isinstance(raw, dict) else []):
                if str(item.get("template_id", "")).strip() == wanted:
                    return item
        except Exception:
            return None
    return None


def _build_merge_payload_result(payload: dict[str, Any]) -> dict[str, Any]:
    raw_sources = payload.get("sources", []) if isinstance(payload, dict) else []
    sources = raw_sources if isinstance(raw_sources, list) else []
    if not sources:
        raise ValueError("sources obbligatorio")
    include_source_tag = bool(payload.get("include_source_tag", True))
    try:
        limit = max(1, int(payload.get("limit", 1000)))
    except Exception:
        limit = 1000
    output_columns = [str(c).strip() for c in (payload.get("output_columns", []) or []) if str(c).strip()]
    merged_rows: list[dict[str, Any]] = []
    discovered: list[str] = []
    sources_preview: list[dict[str, Any]] = []

    for src_cfg in sources:
        if not isinstance(src_cfg, dict):
            continue
        source_id = str(src_cfg.get("source_id", "")).strip()
        if not source_id:
            continue
        source = get_source_by_id(source_id)
        if not source:
            raise ValueError(f"Sorgente non trovata nel merge: {source_id}")
        df = load_dataframe_for_plugin(source)
        calc_defs = src_cfg.get("calculated_fields", [])
        if isinstance(calc_defs, list) and calc_defs:
            rows = df.fillna("").to_dict(orient="records")
            df = pd.DataFrame(apply_calculated_fields(rows, calc_defs))
        cmap = src_cfg.get("column_map", {})
        column_map = cmap if isinstance(cmap, dict) else {}
        source_records = df.fillna("").to_dict(orient="records")
        source_preview_rows: list[dict[str, Any]] = []
        for row in source_records:
            out = {}
            for target_col, src_col in column_map.items():
                tcol = str(target_col).strip()
                scol = str(src_col).strip()
                if not tcol or not scol:
                    continue
                out[tcol] = _merge_json_safe(row.get(scol, ""))
                if tcol not in discovered:
                    discovered.append(tcol)
            if include_source_tag:
                out["_source"] = _merge_json_safe(src_cfg.get("source_tag") or source_id)
                if "_source" not in discovered:
                    discovered.append("_source")
            merged_rows.append(out)
            if len(source_preview_rows) < 3:
                source_preview_rows.append(dict(out))
            if len(merged_rows) >= limit:
                break
        sources_preview.append({
            "source_id": source_id,
            "source_title": str(source.get("title") or source_id),
            "rows_total": len(source_records),
            "rows_preview": source_preview_rows,
        })
        if len(merged_rows) >= limit:
            break

    cols = output_columns or discovered
    rows = [{c: r.get(c, "") for c in cols} for r in merged_rows]
    return {
        "ok": True,
        "columns": cols,
        "rows": rows,
        "row_count": len(rows),
        "truncated": len(merged_rows) >= limit,
        "sources_preview": sources_preview,
    }


def _merge_result_to_csv_bytes(merge_result: dict[str, Any]) -> bytes:
    columns = [str(c) for c in (merge_result.get("columns") or [])]
    rows = merge_result.get("rows") if isinstance(merge_result, dict) else []
    safe_rows = rows if isinstance(rows, list) else []
    out = StringIO()
    writer = csv.DictWriter(out, fieldnames=columns)
    writer.writeheader()
    for row in safe_rows:
        row_data = row if isinstance(row, dict) else {}
        writer.writerow({c: row_data.get(c, "") for c in columns})
    return out.getvalue().encode("utf-8-sig")


def _load_merge_definitions() -> dict[str, Any]:
    path = DATA_DIR / "generated_sources" / "merge_definitions.json"
    raw = read_json(path, {}) or {}
    return raw if isinstance(raw, dict) else {}


def _save_merge_definitions(payload: dict[str, Any]) -> None:
    path = DATA_DIR / "generated_sources" / "merge_definitions.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _source_fingerprint_for_merge(source_id: str) -> dict[str, Any]:
    src = get_source_by_id(source_id) or {}
    path = Path(str(src.get("path") or "")).expanduser()
    stat = path.stat() if path.exists() else None
    return {
        "source_id": source_id,
        "path": str(path),
        "exists": bool(stat),
        "mtime": float(stat.st_mtime) if stat else None,
        "size": int(stat.st_size) if stat else None,
    }


@app.post("/plugin/multi-source-merge/build")
async def merge_build_fallback(request: Request):
    try:
        if not has_plugin_license_access("multi_source_merge"):
            return JSONResponse({"error": "Plugin Multi Source Merge non abilitato dalla licenza."}, status_code=403)
        payload = await request.json()
        return _build_merge_payload_result(payload if isinstance(payload, dict) else {})
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": f"Errore merge: {exc}"}, status_code=500)


@app.post("/plugin/multi-source-merge/export-csv")
async def merge_export_csv_fallback(request: Request):
    try:
        if not has_plugin_license_access("multi_source_merge"):
            return JSONResponse({"error": "Plugin Multi Source Merge non abilitato dalla licenza."}, status_code=403)
        payload = await request.json()
        if not isinstance(payload, dict):
            payload = {}
        merged = _build_merge_payload_result(payload)
        csv_bytes = _merge_result_to_csv_bytes(merged)
        suggested = str(payload.get("filename") or f"merge_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv").strip()
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", suggested) or "merge_export.csv"
        if not safe.lower().endswith(".csv"):
            safe += ".csv"
        headers = {"Content-Disposition": f'attachment; filename="{safe}"'}
        return Response(content=csv_bytes, media_type="text/csv; charset=utf-8", headers=headers)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": f"Errore export CSV merge: {exc}"}, status_code=500)


@app.post("/plugin/multi-source-merge/build-from-template")
async def merge_build_from_template_fallback(request: Request):
    try:
        if not has_plugin_license_access("multi_source_merge"):
            return JSONResponse({"error": "Plugin Multi Source Merge non abilitato dalla licenza."}, status_code=403)
        payload = await request.json()
        if not isinstance(payload, dict):
            payload = {}
        template_id = str(payload.get("template_id", "")).strip()
        tpl = _load_merge_template_record(template_id)
        if not tpl:
            fallback_sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
            if fallback_sources:
                result = _build_merge_payload_result({
                    "sources": fallback_sources,
                    "output_columns": payload.get("output_columns", []),
                    "include_source_tag": payload.get("include_source_tag", True),
                    "limit": payload.get("limit", 1000),
                })
                result["warning"] = f"Template non trovato: {template_id}. Usato mapping corrente del builder."
                return result
            return JSONResponse({"error": "template non trovato"}, status_code=404)
        merged_payload = {
            "sources": payload.get("sources") or tpl.get("sources") or [],
            "output_columns": tpl.get("columns") or [],
            "include_source_tag": payload.get("include_source_tag", tpl.get("include_source_tag", True)),
            "limit": payload.get("limit", 1000),
        }
        result = _build_merge_payload_result(merged_payload)
        result["template_id"] = template_id
        result["template"] = tpl
        return result
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": f"Errore build da template: {exc}"}, status_code=500)


@app.post("/plugin/multi-source-merge/build-and-save-source")
async def merge_build_and_save_fallback(request: Request):
    try:
        if not has_plugin_license_access("multi_source_merge"):
            return JSONResponse({"error": "Plugin Multi Source Merge non abilitato dalla licenza."}, status_code=403)
        payload = await request.json()
        if not isinstance(payload, dict):
            payload = {}
        merged = _build_merge_payload_result(payload)
        source_id = normalize_source_id(payload.get("source_id")) or "1"
        title = str(payload.get("source_title") or f"Merge {source_id}").strip() or f"Merge {source_id}"
        save_mode = str(payload.get("save_mode") or "csv").strip().lower()
        if save_mode not in {"csv", "sqlite"}:
            save_mode = "csv"
        out_dir = DATA_DIR / "generated_sources"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"{source_id}.csv"
        columns = [str(c) for c in (merged.get("columns") or [])]
        rows = merged.get("rows", []) or []
        if save_mode == "sqlite":
            db_path = out_dir / "merge_outputs.db"
            table_name = f"merge_{normalize_source_id(source_id) or '1'}"
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
                col_defs = ", ".join([f'"{c}" TEXT' for c in columns]) if columns else '"value" TEXT'
                conn.execute(f'CREATE TABLE "{table_name}" ({col_defs})')
                if columns:
                    placeholders = ", ".join(["?"] * len(columns))
                    quoted_columns = ", ".join(f'"{c}"' for c in columns)
                    insert_sql = f'INSERT INTO "{table_name}" ({quoted_columns}) VALUES ({placeholders})'
                    conn.executemany(insert_sql, [[str(row.get(c, "")) for c in columns] for row in rows])
        with out_file.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow({c: row.get(c, "") for c in columns})
        import_file = IMPORT_DATA_DIR / f"merge_{source_id}.csv"
        shutil.copyfile(out_file, import_file)
        data = load_sources_data()
        items = data.get("items", [])
        new_item = normalize_source_item(
            {"id": source_id, "title": title, "type": "csv", "path": str(out_file), "delimiter": ",", "encoding": "utf-8-sig"}
        )
        if not new_item:
            raise ValueError("Impossibile creare sorgente merge.")
        replaced = False
        for i, row in enumerate(items):
            if str(row.get("id", "")).strip() == source_id:
                items[i] = new_item
                replaced = True
                break
        if not replaced:
            items.append(new_item)
        data["items"] = items
        if bool(payload.get("set_default")):
            data["default_source"] = source_id
        save_sources_data(data)
        defs = _load_merge_definitions()
        defs[source_id] = {
            "source_id": source_id,
            "title": title,
            "save_mode": save_mode,
            "columns": columns,
            "sources": payload.get("sources") if isinstance(payload.get("sources"), list) else [],
            "updated_at": datetime.utcnow().isoformat(),
            "source_fingerprints": [
                _source_fingerprint_for_merge(str(s.get("source_id", "")).strip())
                for s in (payload.get("sources") if isinstance(payload.get("sources"), list) else [])
                if isinstance(s, dict) and str(s.get("source_id", "")).strip()
            ],
            "import_data_path": str(import_file),
        }
        _save_merge_definitions(defs)
        return {"ok": True, "source": new_item, "merge": merged, "save_mode": save_mode}
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": f"Errore salvataggio sorgente merge: {exc}"}, status_code=500)

plugin_manager = PluginManager(
    get_plugin_roots(),
    enabled_map=load_plugins_enabled_map(),
)

plugin_api = PluginAPI(
    get_source=get_source_by_id,
    load_dataframe_from_source=load_dataframe_for_plugin,
    get_sources_bundle=load_sources_data,
    get_runtime_paths=get_runtime_paths,
    get_license_context=get_license_context,
    compute_pivot_result=plugin_compute_pivot_result,
)

plugin_manager.load_all(app, plugin_api)

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    customer_logo_url = get_customer_logo_url() if CUSTOMER_LOGO_PATH.exists() else ""
    ctx = {
        "request": request,
        "current_user": get_current_user_from_session(request),
        "customer_logo_url": customer_logo_url,
        **get_license_context(),
    }
    return templates.TemplateResponse("index.html", ctx)


@app.get("/branding/customer-logo")
def branding_customer_logo():
    if not CUSTOMER_LOGO_PATH.exists():
        return RedirectResponse("/static/img/pivotdesk-logo.png", status_code=307)
    meta = get_customer_logo_meta()
    media_type = str(meta.get("content_type") or "").strip() or None
    return FileResponse(CUSTOMER_LOGO_PATH, media_type=media_type)


@app.post("/admin/branding/customer-logo")
async def admin_upload_customer_logo(request: Request, file: UploadFile = File(...)):
    current_user = require_admin(request)
    if not current_user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=403)

    ctx = get_license_context(prefer_online=False)
    status = str(ctx.get("license_status", "demo")).strip().lower() or "demo"
    if not license_allows_lan_access(status):
        return JSONResponse({"error": "Upload logo cliente disponibile solo con licenza attiva."}, status_code=403)

    content_type = str(file.content_type or "").lower()
    if not content_type.startswith("image/"):
        return JSONResponse({"error": "Formato non valido. Carica un file immagine."}, status_code=400)

    payload = await file.read()
    if not payload or len(payload) > (2 * 1024 * 1024):
        return JSONResponse({"error": "File assente o troppo grande (max 2MB)."}, status_code=400)

    BRANDING_DIR.mkdir(parents=True, exist_ok=True)
    CUSTOMER_LOGO_PATH.write_bytes(payload)
    write_json(
        CUSTOMER_LOGO_META_PATH,
        {
            "content_type": content_type,
            "uploaded_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "uploaded_by": str(current_user.get("username", "admin")),
            "size": len(payload),
        },
    )
    return {"ok": True, "logo_url": get_customer_logo_url()}


@app.get("/license/status")
def license_status(prefer_online: bool = Query(False)):
    ctx = get_license_context(prefer_online=prefer_online)
    ctx["available_providers"] = get_available_license_providers()
    ctx["multistore_available"] = MULTISTORE_LICENSE_AVAILABLE
    return ctx


@app.get("/license/providers")
def license_providers():
    settings = load_license_settings()
    return {
        "multistore_available": MULTISTORE_LICENSE_AVAILABLE,
        "providers": get_available_license_providers(),
        "settings": {
            "developer": {"enabled": bool(settings.get("developer", {}).get("enabled", True))},
            "gumroad": {"enabled": bool(settings.get("gumroad", {}).get("enabled", False)), "product_id": settings.get("gumroad", {}).get("product_id", "")},
            "lemonsqueezy": {"enabled": bool(settings.get("lemonsqueezy", {}).get("enabled", False)), "product_id": settings.get("lemonsqueezy", {}).get("product_id", ""), "variant_id": settings.get("lemonsqueezy", {}).get("variant_id", "")},
            "custom": {"enabled": bool(settings.get("custom", {}).get("enabled", False)), "activate_url": settings.get("custom", {}).get("activate_url", "")},
        },
    }


@app.get("/lan/status")
def lan_status(request: Request):
    current_user = require_login(request)
    if not current_user:
        return JSONResponse({"error": "Non autenticato"}, status_code=401)

    ctx = get_license_context(prefer_online=False)
    cfg = load_config()
    configured_host = str(cfg.get("host", "127.0.0.1") or "127.0.0.1").strip() or "127.0.0.1"
    configured_port = int(cfg.get("port", 8091))

    status = str(ctx.get("license_status", "demo")).strip().lower() or "demo"
    lan_by_license = license_allows_lan_access(status)

    effective_bind_host, port, bind_source = resolve_lan_bind_info(
        configured_host=configured_host,
        configured_port=configured_port,
        lan_by_license=lan_by_license,
    )

    public_lan_host = resolve_public_lan_host()
    lan_host = public_lan_host
    lan_enabled = effective_bind_host in {"0.0.0.0", "::"}
    loopback_reachable = can_connect_to_host_port("127.0.0.1", port)
    lan_reachable_from_host = can_connect_to_host_port(lan_host, port)
    firewall_hint = "Se lan_enabled=true ma non raggiungibile da altri PC, verificare firewall/antivirus/router (client isolation)."
    if bind_source == "inferred":
        firewall_hint += " Nota: bind effettivo inferito da licenza/config; se il processo è partito con host diverso (es. 127.0.0.1) la LAN resterà non raggiungibile."
    if lan_by_license and not lan_enabled:
        firewall_hint += " Licenza LAN attiva ma processo in ascolto locale-only: riavvio richiesto con host 0.0.0.0."
    if lan_enabled and loopback_reachable and not lan_reachable_from_host:
        firewall_hint += " Diagnostica locale: 127.0.0.1 risponde ma IP LAN rifiuta la connessione; probabile avvio server su host locale-only (127.0.0.1)."

    startup_hint = ""
    if lan_by_license and not lan_enabled:
        startup_hint = (
            "Licenza abilita LAN ma il processo corrente è su localhost. "
            "Riavvia da launcher (`python run_pivotdesk.py`) o con uvicorn `--host 0.0.0.0`."
        )
    elif lan_enabled and loopback_reachable and not lan_reachable_from_host:
        startup_hint = (
            "Avvia PivotDesk con bind LAN esplicito (es. variabile PIVOTDESK_HOST=0.0.0.0 "
            "oppure uvicorn con --host 0.0.0.0)."
        )

    return {
        "ok": True,
        "license_status": status,
        "license_label": ctx.get("license_label", "N/D"),
        "configured_host": configured_host,
        "configured_port": configured_port,
        "effective_bind_host": effective_bind_host,
        "bind_source": bind_source,
        "port": port,
        "lan_expected_by_license": lan_by_license,
        "lan_enabled": lan_enabled,
        "loopback_reachable": loopback_reachable,
        "lan_reachable_from_host": lan_reachable_from_host,
        "loopback_url": f"http://127.0.0.1:{port}/",
        "lan_url": f"http://{lan_host}:{port}/",
        "firewall_hint": firewall_hint,
        "startup_hint": startup_hint,
    }


@app.post("/lan/probe/new")
def lan_probe_new(request: Request):
    current_user = require_login(request)
    if not current_user:
        return JSONResponse({"error": "Non autenticato"}, status_code=401)

    cleanup_lan_probes()

    ctx = get_license_context(prefer_online=False)
    cfg = load_config()
    configured_host = str(cfg.get("host", "127.0.0.1") or "127.0.0.1").strip() or "127.0.0.1"
    configured_port = int(cfg.get("port", 8091))
    status = str(ctx.get("license_status", "demo")).strip().lower() or "demo"
    lan_by_license = license_allows_lan_access(status)

    effective_bind_host, port, _ = resolve_lan_bind_info(
        configured_host=configured_host,
        configured_port=configured_port,
        lan_by_license=lan_by_license,
    )
    if effective_bind_host not in {"0.0.0.0", "::"}:
        return JSONResponse(
            {
                "ok": False,
                "error": "LAN non attiva su questo avvio.",
                "manual_hint": "Riavvia l'app tramite launcher (`python run_pivotdesk.py`) oppure avvia uvicorn con `--host 0.0.0.0`.",
            },
            status_code=400,
        )

    lan_host = resolve_public_lan_host() if effective_bind_host == "0.0.0.0" else effective_bind_host
    probe_id = uuid.uuid4().hex
    LAN_PROBES[probe_id] = {
        "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "created_ts": datetime.utcnow().timestamp(),
        "created_by": str(current_user.get("username", "unknown")),
        "hits": [],
    }
    return {
        "ok": True,
        "probe_id": probe_id,
        "probe_url": f"http://{lan_host}:{port}/lan/probe/{probe_id}",
        "lan_url": f"http://{lan_host}:{port}/",
    }


@app.get("/lan/probe/{probe_id}")
def lan_probe_ping(probe_id: str, request: Request):
    cleanup_lan_probes()
    data = LAN_PROBES.get(str(probe_id).strip())
    if not data:
        return JSONResponse({"ok": False, "error": "Probe non trovata o scaduta"}, status_code=404)

    hit = {
        "at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "remote": request.client.host if request.client else "",
        "user_agent": str(request.headers.get("user-agent", "")),
    }
    hits = data.get("hits", [])
    if isinstance(hits, list):
        hits.append(hit)
        data["hits"] = hits[-10:]
    else:
        data["hits"] = [hit]
    return {"ok": True, "probe_id": probe_id, "message": "LAN probe raggiunta"}


@app.get("/lan/probe/status")
def lan_probe_status(request: Request, probe_id: str = Query(...)):
    current_user = require_login(request)
    if not current_user:
        return JSONResponse({"error": "Non autenticato"}, status_code=401)

    cleanup_lan_probes()
    data = LAN_PROBES.get(str(probe_id).strip())
    if not data:
        return JSONResponse({"ok": False, "error": "Probe non trovata o scaduta"}, status_code=404)

    hits = data.get("hits", [])
    latest = hits[-1] if isinstance(hits, list) and hits else None
    return {
        "ok": True,
        "probe_id": probe_id,
        "created_at": data.get("created_at"),
        "hit_count": len(hits) if isinstance(hits, list) else 0,
        "last_hit": latest,
        "reachable": bool(hits),
    }


@app.get("/lan/probe/result")
def lan_probe_result(request: Request, probe_id: str = Query(...)):
    return lan_probe_status(request=request, probe_id=probe_id)


@app.get("/lan/probe_check")
def lan_probe_check(request: Request, probe_id: str = Query(...)):
    return lan_probe_status(request=request, probe_id=probe_id)


@app.post("/lan/firewall/open")
async def lan_firewall_open(request: Request):
    current_user = require_admin(request)
    if not current_user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=403)

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    cfg = load_config()
    port = int(payload.get("port", cfg.get("port", 8091)))
    auto_elevate = bool(payload.get("auto_elevate", True))
    system_name = platform.system().lower()

    commands: list[list[str]] = []
    if system_name == "windows":
        commands.append([
            "netsh", "advfirewall", "firewall", "add", "rule",
            f"name=PivotDesk {port}",
            "dir=in",
            "action=allow",
            "protocol=TCP",
            f"localport={port}",
        ])
    elif system_name == "linux":
        if shutil.which("ufw"):
            commands.append(["ufw", "allow", f"{port}/tcp"])
    elif system_name == "darwin":
        return JSONResponse(
            {
                "ok": False,
                "error": "Apertura firewall automatica non supportata su macOS da questa build.",
                "manual_hint": f"Consenti l'app Python nel firewall macOS oppure apri la porta TCP {port}.",
            },
            status_code=400,
        )

    if not commands:
        return JSONResponse(
            {
                "ok": False,
                "error": "Nessun comando firewall disponibile per questa piattaforma.",
                "manual_hint": f"Apri manualmente la porta TCP {port} in ingresso.",
            },
            status_code=400,
        )

    last_error = ""
    for cmd in commands:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode == 0:
                return {
                    "ok": True,
                    "platform": system_name,
                    "port": port,
                    "command": " ".join(cmd),
                    "message": (proc.stdout or "Regola firewall applicata.").strip(),
                    "stdout": (proc.stdout or "").strip(),
                    "stderr": (proc.stderr or "").strip(),
                }
            raw_error = (proc.stderr or proc.stdout or "").strip()
            low_error = raw_error.lower()
            if "already exists" in low_error or "esiste già" in low_error:
                return {
                    "ok": True,
                    "platform": system_name,
                    "port": port,
                    "command": " ".join(cmd),
                    "message": "Regola firewall già presente.",
                }
            last_error = raw_error
        except Exception as exc:
            last_error = str(exc)

    if system_name == "windows" and auto_elevate:
        try:
            import ctypes

            arg_line = (
                f"advfirewall firewall add rule name=\"PivotDesk {port}\" "
                f"dir=in action=allow protocol=TCP localport={port}"
            )
            # ShellExecuteW con verbo runas mostra il prompt UAC nativo.
            result = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                "netsh",
                arg_line,
                None,
                1,
            )
            if int(result) <= 32:
                raise RuntimeError(f"ShellExecuteW errore: {result}")
            time.sleep(1.0)
            return {
                "ok": True,
                "platform": system_name,
                "port": port,
                "pending_elevation": True,
                "command": f"netsh {arg_line}",
                "message": "Richiesta di elevazione inviata. Conferma il prompt UAC per completare l'apertura firewall.",
                "manual_hint": f"Dopo il consenso UAC, ripeti il test LAN sulla porta {port}.",
            }
        except Exception as exc:
            if not last_error:
                last_error = str(exc)

    return JSONResponse(
        {
            "ok": False,
            "platform": system_name,
            "port": port,
            "error": last_error or "Impossibile applicare regola firewall.",
            "manual_hint": f"Esegui l'app come amministratore e apri la porta TCP {port} in ingresso.",
        },
        status_code=500,
    )


@app.post("/license/activate")
async def license_activate(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    provider_name = str(payload.get("provider") or payload.get("provider_name") or "developer").strip().lower()
    email = str(payload.get("email") or "").strip()
    license_key = str(payload.get("license_key") or payload.get("key") or "").strip()

    if not license_key:
        return JSONResponse({"ok": False, "error": "license_key obbligatoria"}, status_code=400)

    manager = build_license_manager()
    if not manager:
        return JSONResponse({"ok": False, "error": "Sistema di licensing non disponibile"}, status_code=500)

    if provider_name not in manager.providers:
        return JSONResponse({"ok": False, "error": f"Provider non disponibile: {provider_name}", "providers": sorted(manager.providers.keys())}, status_code=400)

    result = manager.activate(provider_name=provider_name, email=email, license_key=license_key)
    status_code = 200 if result.ok else 400
    response = {
        "ok": result.ok,
        "message": result.message,
        "error_code": result.error_code,
        "provider": provider_name,
        "license": result.record.__dict__ if result.record else None,
        "context": get_license_context(prefer_online=False),
    }
    return JSONResponse(response, status_code=status_code)


@app.post("/license/validate")
def license_validate(prefer_online: bool = Query(True)):
    manager = build_license_manager()
    if not manager:
        return JSONResponse({"ok": False, "error": "Sistema di licensing non disponibile"}, status_code=500)

    result = manager.validate_current(prefer_online=prefer_online)
    status_code = 200 if result.ok else 400
    return JSONResponse({
        "ok": result.ok,
        "message": result.message,
        "error_code": result.error_code,
        "license": result.record.__dict__ if result.record else None,
        "context": get_license_context(prefer_online=False),
    }, status_code=status_code)


@app.post("/license/deactivate")
def license_deactivate():
    manager = build_license_manager()
    if not manager:
        return JSONResponse({"ok": False, "error": "Sistema di licensing non disponibile"}, status_code=500)

    result = manager.deactivate_current()
    status_code = 200 if result.ok else 400
    return JSONResponse({
        "ok": result.ok,
        "message": result.message,
        "error_code": result.error_code,
        "license": result.record.__dict__ if result.record else None,
        "context": get_license_context(prefer_online=False),
    }, status_code=status_code)


@app.post("/dev/license/create")
def dev_license_create():
    if not is_dev_runtime():
        return JSONResponse({"error": "Operazione non consentita in runtime distribuito"}, status_code=403)

    data = create_dev_license_file()
    return {
        "ok": True,
        "message": "Licenza dev creata correttamente",
        "path": str(DEV_LICENSE_PATH),
        "license": data,
    }


@app.post("/dev/license/delete")
def dev_license_delete():
    if not is_dev_runtime():
        return JSONResponse({"error": "Operazione non consentita in runtime distribuito"}, status_code=403)

    try:
        if DEV_LICENSE_PATH.exists():
            DEV_LICENSE_PATH.unlink()
        return {"ok": True, "message": "Licenza dev rimossa"}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str | None = None):
    user = get_current_user_from_session(request)
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": error})


@app.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    user = find_user(username)
    if not user or not bool(user.get("enabled", True)) or user.get("password_hash") != hash_password(password):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Credenziali non valide"},
            status_code=401,
        )
    request.session["username"] = str(user.get("username", "")).strip()
    return RedirectResponse("/", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def admin_users_page(request: Request):
    current_user = require_admin(request)
    if not current_user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse("admin_users.html", {"request": request, "current_user": current_user})


@app.get("/admin/users")
def admin_users_list(request: Request):
    current_user = require_admin(request)
    if not current_user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=403)
    items = [public_user(x) for x in load_users_data().get("items", [])]
    return {"items": items}


@app.post("/admin/users/create")
async def admin_users_create(request: Request):
    current_user = require_admin(request)
    if not current_user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=403)

    payload = await request.json()
    username = normalize_source_id(payload.get("username"))
    display_name = str(payload.get("display_name", "")).strip() or username
    role = str(payload.get("role", "user")).strip().lower() or "user"
    password = str(payload.get("password", "")).strip()

    if not username:
        return JSONResponse({"error": "Username obbligatorio"}, status_code=400)
    if not password:
        return JSONResponse({"error": "Password obbligatoria"}, status_code=400)
    if role not in {"admin", "user"}:
        role = "user"

    data = load_users_data()
    if any(str(x.get("username", "")).strip().lower() == username for x in data.get("items", [])):
        return JSONResponse({"error": "Username già esistente"}, status_code=400)

    data["items"].append({
        "username": username,
        "display_name": display_name,
        "role": role,
        "enabled": True,
        "password_hash": hash_password(password),
    })
    save_users_data(data)
    return {"ok": True, "items": [public_user(x) for x in data.get("items", [])]}


@app.post("/admin/users/toggle")
async def admin_users_toggle(request: Request):
    current_user = require_admin(request)
    if not current_user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=403)

    payload = await request.json()
    username = normalize_source_id(payload.get("username"))
    data = load_users_data()
    changed = False

    for user in data.get("items", []):
        if str(user.get("username", "")).strip().lower() == username:
            if username == str(current_user.get("username", "")).strip().lower():
                return JSONResponse({"error": "Non puoi disabilitare il tuo utente corrente"}, status_code=400)
            user["enabled"] = not bool(user.get("enabled", True))
            changed = True
            break

    if not changed:
        return JSONResponse({"error": "Utente non trovato"}, status_code=404)

    save_users_data(data)
    return {"ok": True, "items": [public_user(x) for x in data.get("items", [])]}


@app.post("/admin/users/reset-password")
async def admin_users_reset_password(request: Request):
    current_user = require_admin(request)
    if not current_user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=403)

    payload = await request.json()
    username = normalize_source_id(payload.get("username"))
    password = str(payload.get("password", "")).strip()
    if not password:
        return JSONResponse({"error": "Password obbligatoria"}, status_code=400)

    data = load_users_data()
    changed = False
    for user in data.get("items", []):
        if str(user.get("username", "")).strip().lower() == username:
            user["password_hash"] = hash_password(password)
            changed = True
            break

    if not changed:
        return JSONResponse({"error": "Utente non trovato"}, status_code=404)

    save_users_data(data)
    return {"ok": True}

@app.get("/health")
def health():
    cfg = load_config()
    return {
        "ok": True,
        "app_name": cfg.get("app_name", "PivotDesk"),
        "host": cfg.get("host", "127.0.0.1"),
        "port": cfg.get("port", 8091),
    }


@app.get("/wiki/content")
def wiki_content(lang: str = Query("it")):
    code = str(lang or "it").strip().lower()
    target = BASE_DIR / "docs" / ("WIKI.md" if code == "en" else "WIKI.it.md")
    if not target.exists():
        return JSONResponse({"error": "Wiki file not found"}, status_code=404)
    return {
        "ok": True,
        "lang": "en" if code == "en" else "it",
        "content": target.read_text(encoding="utf-8", errors="ignore"),
    }


@app.get("/wiki/assets/{asset_path:path}")
def wiki_asset(asset_path: str):
    rel = Path(str(asset_path or "").strip())
    if rel.is_absolute() or ".." in rel.parts:
        return JSONResponse({"error": "Invalid asset path"}, status_code=400)
    target = (BASE_DIR / "docs" / rel).resolve()
    docs_root = (BASE_DIR / "docs").resolve()
    if not str(target).startswith(str(docs_root)) or not target.exists() or not target.is_file():
        return JSONResponse({"error": "Asset not found"}, status_code=404)
    return FileResponse(str(target))


@app.get("/plugins")
def plugins_registry():
    return plugin_manager.get_frontend_registry()


@app.get("/plugins/status")
def plugins_status():
    status_payload = plugin_manager.get_status()
    license_allows_plugins = has_plugin_license_access("")
    enabled_map = load_plugins_enabled_map()

    plugins = status_payload.get("items", []) if isinstance(status_payload, dict) else []
    if isinstance(plugins, list):
        for item in plugins:
            if not isinstance(item, dict):
                continue
            plugin_id = str(item.get("id", "")).strip()
            runtime_enabled = bool(item.get("enabled"))
            configured_enabled = enabled_map.get(plugin_id, runtime_enabled)
            license_allowed = has_plugin_license_access(plugin_id)
            item["runtime_enabled"] = runtime_enabled
            item["configured_enabled"] = bool(configured_enabled)
            item["license_allowed"] = bool(license_allowed)
            item["license_features"] = [plugin_id, f"plugin_{plugin_id}", f"plugins.{plugin_id}", "plugins"]
            item["effective_enabled"] = bool(configured_enabled and license_allowed)

    if isinstance(status_payload, dict):
        status_payload["plugins"] = plugins
        status_payload["license_plugins_allowed"] = license_allows_plugins
        status_payload["configured_enabled_map"] = enabled_map
    return status_payload


@app.post("/plugins/config/save")
async def plugins_config_save(request: Request):
    current_user = require_admin(request)
    if not current_user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=403)
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    enabled_raw = payload.get("enabled", {}) if isinstance(payload, dict) else {}
    if not isinstance(enabled_raw, dict):
        return JSONResponse({"error": "Formato non valido: enabled deve essere un oggetto."}, status_code=400)

    saved_map = save_plugins_enabled_map({str(k): bool(v) for k, v in enabled_raw.items()})
    return {
        "ok": True,
        "enabled": saved_map,
        "restart_required": True,
        "message": "Configurazione plugin salvata. Riavvia PivotDesk per applicare eventuali cambi di routing.",
    }


@app.get("/settings")
def settings_get(request: Request):
    if not require_login(request):
        return JSONResponse({"error": "Non autenticato"}, status_code=401)
    return {"settings": load_settings_data()}


@app.post("/settings/save")
async def settings_save(request: Request):
    if not require_login(request):
        return JSONResponse({"error": "Non autenticato"}, status_code=401)
    try:
        payload = await request.json()
        data = save_settings_data(payload or {})
        return {"ok": True, "settings": data}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/admin/backup/export")
def admin_backup_export(request: Request):
    current_user = require_admin(request)
    if not current_user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=403)
    if not has_license_feature("backup_restore"):
        return JSONResponse({"error": "Funzione disponibile solo con licenza attiva."}, status_code=403)

    return {"ok": True, "backup": build_backup_payload()}


@app.post("/admin/backup/restore")
async def admin_backup_restore(request: Request):
    current_user = require_admin(request)
    if not current_user:
        return JSONResponse({"error": "Non autorizzato"}, status_code=403)
    if not has_license_feature("backup_restore"):
        return JSONResponse({"error": "Funzione disponibile solo con licenza attiva."}, status_code=403)

    try:
        payload = await request.json()
        backup = payload.get("backup", payload) if isinstance(payload, dict) else {}
        if not isinstance(backup, dict):
            return JSONResponse({"error": "Payload backup non valido."}, status_code=400)

        replace_existing = bool(payload.get("replace_existing", True)) if isinstance(payload, dict) else True
        result = restore_backup_payload(backup, replace_existing=replace_existing)
        return {"ok": True, **result}
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/sources")
def sources_get(request: Request):
    if not require_login(request):
        return JSONResponse({"error": "Non autenticato"}, status_code=401)
    try:
        data = load_sources_data()
        return {
            "items": data.get("items", []),
            "default_source": data.get("default_source", ""),
        }
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/sources/scan-import-data")
async def sources_scan_import_data(request: Request):
    if not require_login(request):
        return JSONResponse({"error": "Non autenticato"}, status_code=401)
    try:
        data = load_sources_data()
        items = data.get("items", []) if isinstance(data, dict) else []
        imported = [
            x for x in items
            if isinstance(x, dict) and bool((x.get("config") if isinstance(x.get("config"), dict) else {}).get("auto_import_data"))
        ]
        return {"ok": True, "import_data_dir": str(IMPORT_DATA_DIR), "imported_count": len(imported), "items": imported}
    except Exception as exc:
        return JSONResponse({"error": f"Errore scansione import_data: {exc}"}, status_code=500)


@app.post("/sources/save")
async def sources_save(request: Request):
    if not require_login(request):
        return JSONResponse({"error": "Non autenticato"}, status_code=401)
    try:
        payload = await request.json()
        data = load_sources_data()

        src_id = normalize_source_id(payload.get("id"))
        title = str(payload.get("title", "")).strip() or src_id
        src_type = str(payload.get("type", "csv")).strip().lower() or "csv"
        if src_type in {"google_drive", "google_sheet"}:
            src_type = "gdrive"
        path = str(payload.get("path", "")).strip()
        make_default = bool(payload.get("make_default", False))
        config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
        source_calculated_fields = sanitize_calculated_fields(
            payload.get("calculated_fields", config.get("calculated_fields", []))
        )

        if not src_id:
            return JSONResponse({"error": "ID sorgente obbligatorio"}, status_code=400)

        if not path and not config:
            return JSONResponse({"error": "Configurazione sorgente obbligatoria"}, status_code=400)

        if path and "path" not in config:
            config["path"] = path

        items = data.get("items", [])
        existing = next((x for x in items if x["id"] == src_id), None)

        delimiter = str(payload.get("delimiter", "") or "").strip()
        encoding = str(payload.get("encoding", "") or "").strip()
        sheet_name = str(payload.get("sheet_name", "") or "").strip()
        try:
            skip_rows = max(int(payload.get("skip_rows", 0) or 0), 0)
        except Exception:
            skip_rows = 0

        if delimiter:
            config["delimiter"] = delimiter
        else:
            config.pop("delimiter", None)

        if encoding:
            config["encoding"] = encoding
        else:
            config.pop("encoding", None)

        if sheet_name:
            config["sheet_name"] = sheet_name
        else:
            config.pop("sheet_name", None)

        config["skip_rows"] = skip_rows
        if source_calculated_fields:
            config["calculated_fields"] = source_calculated_fields
        else:
            config.pop("calculated_fields", None)

        record = {
            "id": src_id,
            "title": title,
            "type": src_type,
            "path": path,
            "delimiter": delimiter,
            "encoding": encoding,
            "sheet_name": sheet_name,
            "skip_rows": skip_rows,
            "config": config,
        }
        if source_calculated_fields:
            record["calculated_fields"] = source_calculated_fields
        else:
            record.pop("calculated_fields", None)

        if existing:
            existing.update(record)
        else:
            items.append(record)

        if make_default or not data.get("default_source"):
            data["default_source"] = src_id

        saved = save_sources_data(data)
        clear_source_dataframe_cache(src_id)
        source_folder(src_id)

        return {
            "ok": True,
            "items": saved.get("items", []),
            "default_source": saved.get("default_source", ""),
        }

    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/sources/delete")
async def sources_delete(request: Request):
    if not require_login(request):
        return JSONResponse({"error": "Non autenticato"}, status_code=401)
    try:
        payload = await request.json()
        source_id = normalize_source_id(payload.get("source_id"))

        if not source_id:
            return JSONResponse({"error": "source_id obbligatorio"}, status_code=400)

        data = load_sources_data()
        items = [x for x in data.get("items", []) if x["id"] != source_id]
        data["items"] = items

        if data.get("default_source") == source_id:
            data["default_source"] = items[0]["id"] if items else ""

        saved = save_sources_data(data)
        clear_source_dataframe_cache(source_id)

        return {
            "ok": True,
            "items": saved.get("items", []),
            "default_source": saved.get("default_source", ""),
        }

    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)




@app.post("/sources/upload")
async def sources_upload(request: Request, file: UploadFile = File(...)):
    current_user = require_login(request)
    if not current_user:
        return JSONResponse({"error": "Non autenticato"}, status_code=401)
    return JSONResponse(
        {
            "error": "Upload file disabilitato: usa la selezione percorso locale, senza copia nel folder programma."
        },
        status_code=410,
    )


@app.post("/sources/pick-local-file")
async def sources_pick_local_file(request: Request):
    current_user = require_login(request)
    if not current_user:
        return JSONResponse({"error": "Non autenticato"}, status_code=401)

    selected = ""
    last_error = ""
    cancelled = False

    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.title("PivotDesk")
        try:
            icon_path = resource_path("static", "img", "pivotdesk-icon.png")
            if icon_path.exists():
                icon_img = tk.PhotoImage(file=str(icon_path))
                root.iconphoto(True, icon_img)
                root._icon_img = icon_img  # keep reference alive
        except Exception:
            pass
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        try:
            root.update_idletasks()
            root.deiconify()
            root.lift()
            root.focus_force()
            root.update()
        except Exception:
            pass
        selected = filedialog.askopenfilename(
            title="Seleziona sorgente dati",
            parent=root,
            filetypes=[
                ("File dati", "*.csv *.xlsx *.xls *.xlsm"),
                ("CSV", "*.csv"),
                ("Excel", "*.xlsx *.xls *.xlsm"),
                ("Tutti i file", "*.*"),
            ],
        )
        try:
            root.destroy()
        except Exception:
            pass
    except Exception as exc:
        last_error = str(exc)

    if not selected and os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class OPENFILENAMEW(ctypes.Structure):
                _fields_ = [
                    ("lStructSize", wintypes.DWORD),
                    ("hwndOwner", wintypes.HWND),
                    ("hInstance", wintypes.HINSTANCE),
                    ("lpstrFilter", wintypes.LPCWSTR),
                    ("lpstrCustomFilter", wintypes.LPWSTR),
                    ("nMaxCustFilter", wintypes.DWORD),
                    ("nFilterIndex", wintypes.DWORD),
                    ("lpstrFile", wintypes.LPWSTR),
                    ("nMaxFile", wintypes.DWORD),
                    ("lpstrFileTitle", wintypes.LPWSTR),
                    ("nMaxFileTitle", wintypes.DWORD),
                    ("lpstrInitialDir", wintypes.LPCWSTR),
                    ("lpstrTitle", wintypes.LPCWSTR),
                    ("Flags", wintypes.DWORD),
                    ("nFileOffset", wintypes.WORD),
                    ("nFileExtension", wintypes.WORD),
                    ("lpstrDefExt", wintypes.LPCWSTR),
                    ("lCustData", wintypes.LPARAM),
                    ("lpfnHook", wintypes.LPVOID),
                    ("lpTemplateName", wintypes.LPCWSTR),
                    ("pvReserved", wintypes.LPVOID),
                    ("dwReserved", wintypes.DWORD),
                    ("FlagsEx", wintypes.DWORD),
                ]

            OFN_FILEMUSTEXIST = 0x00001000
            OFN_PATHMUSTEXIST = 0x00000800
            OFN_HIDEREADONLY = 0x00000004

            file_buffer = ctypes.create_unicode_buffer(65535)
            file_filter = (
                "File dati (*.csv;*.xlsx;*.xls;*.xlsm)\0*.csv;*.xlsx;*.xls;*.xlsm\0"
                "CSV (*.csv)\0*.csv\0"
                "Excel (*.xlsx;*.xls;*.xlsm)\0*.xlsx;*.xls;*.xlsm\0"
                "Tutti i file (*.*)\0*.*\0\0"
            )

            ofn = OPENFILENAMEW()
            ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
            ofn.lpstrFilter = file_filter
            ofn.lpstrFile = ctypes.cast(file_buffer, wintypes.LPWSTR)
            ofn.nMaxFile = len(file_buffer)
            ofn.lpstrTitle = "Seleziona sorgente dati"
            ofn.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_HIDEREADONLY

            result = ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(ofn))
            if result:
                selected = file_buffer.value
            else:
                dlg_error = ctypes.windll.comdlg32.CommDlgExtendedError()
                if int(dlg_error) == 0:
                    cancelled = True
                else:
                    last_error = f"Errore WinAPI dialog ({int(dlg_error)})"
        except Exception as exc:
            last_error = str(exc)

    if not selected and sys.platform == "darwin":
        try:
            proc = subprocess.run(
                [
                    "osascript",
                    "-e",
                    'POSIX path of (choose file with prompt "Seleziona sorgente dati")',
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode == 0:
                selected = (proc.stdout or "").strip()
            elif proc.returncode in {1, 256}:
                cancelled = True
            elif proc.stderr:
                last_error = (proc.stderr or "").strip()
        except Exception as exc:
            last_error = str(exc)

    if not selected and sys.platform.startswith("linux"):
        try:
            if shutil.which("zenity"):
                proc = subprocess.run(
                    [
                        "zenity",
                        "--file-selection",
                        "--title=Seleziona sorgente dati",
                        "--file-filter=File dati | *.csv *.xlsx *.xls *.xlsm",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if proc.returncode == 0:
                    selected = (proc.stdout or "").strip()
                elif proc.returncode == 1:
                    cancelled = True
            elif shutil.which("kdialog"):
                proc = subprocess.run(
                    [
                        "kdialog",
                        "--getopenfilename",
                        "",
                        "*.csv *.xlsx *.xls *.xlsm",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if proc.returncode == 0:
                    selected = (proc.stdout or "").strip()
                elif proc.returncode == 1:
                    cancelled = True
        except Exception as exc:
            last_error = str(exc)

    if not selected and cancelled:
        return {"ok": False, "cancelled": True}

    if not selected and last_error:
        return JSONResponse(
            {"error": f"Impossibile aprire il selettore file locale: {last_error}"},
            status_code=500,
        )

    if not selected:
        return JSONResponse(
            {
                "error": "Nessun file selezionato o selettore non disponibile su questa piattaforma. Usa 'Incolla percorso'."
            },
            status_code=400,
        )

    path = Path(selected)
    ext = path.suffix.lower()
    source_type = "xlsx" if ext in {".xlsx", ".xlsm", ".xls"} else "csv"
    resolved_info = (
        "Excel · foglio: primo foglio"
        if source_type == "xlsx"
        else "CSV · delimitatore: auto · encoding: auto"
    )

    return {
        "ok": True,
        "filename": path.name,
        "path": str(path),
        "source_type": source_type,
        "delimiter": "",
        "encoding": "",
        "sheet_name": "",
        "resolved_info": resolved_info,
    }


@app.get("/source-preview")
def source_preview(
    request: Request,
    source_id: str = Query(...),
    limit: int = Query(20),
    pivot_id: str | None = Query(None),
    calculated_fields: str | None = Query(None),
):
    current_user = require_login(request)
    if not current_user:
        return JSONResponse({"error": "Non autenticato"}, status_code=401)
    try:
        src, df = load_source_df(source_id)
        if calculated_fields:
            try:
                raw = json.loads(calculated_fields)
            except Exception:
                raw = []
            df = apply_calculated_fields_to_dataframe(df, sanitize_calculated_fields(raw if isinstance(raw, list) else []))
        elif pivot_id:
            df = apply_preset_calculated_fields(df, pivot_id=pivot_id, source_id=source_id)
        return build_dataframe_preview_payload(src, df, limit=limit)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/source-preview-form")
async def source_preview_from_form_alias(request: Request, limit: int = Query(20)):
    return await source_preview_from_form(request, limit)


@app.get("/source-sheets")
def source_sheets(request: Request, source_id: str = Query(...)):
    current_user = require_login(request)
    if not current_user:
        return JSONResponse({"error": "Non autenticato"}, status_code=401)
    try:
        src = get_source_by_id(source_id)
        src_type = str(src.get("type", "")).strip().lower()
        if src_type not in {"xlsx", "xls", "xlsm", "excel"}:
            return JSONResponse({"error": "La sorgente selezionata non è Excel."}, status_code=400)
        path = str(src.get("path") or src.get("config", {}).get("path") or "").strip()
        if not path:
            return JSONResponse({"error": "Percorso file non configurato."}, status_code=400)
        sheets = list_excel_sheet_names(path)
        return {"ok": True, "source_id": source_id, "sheets": sheets}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/source-sheets/form")
async def source_sheets_from_form(request: Request):
    current_user = require_login(request)
    if not current_user:
        return JSONResponse({"error": "Non autenticato"}, status_code=401)
    try:
        payload = await request.json()
        source = build_source_from_payload(payload if isinstance(payload, dict) else {})
        src_type = str(source.get("type", "")).strip().lower()
        if src_type not in {"xlsx", "xls", "xlsm", "excel"}:
            return JSONResponse({"error": "Seleziona tipo sorgente Excel per leggere i fogli."}, status_code=400)
        path = str(source.get("path") or source.get("config", {}).get("path") or "").strip()
        if not path:
            return JSONResponse({"error": "Percorso file obbligatorio."}, status_code=400)
        sheets = list_excel_sheet_names(path)
        return {"ok": True, "sheets": sheets}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/source-preview/form")
async def source_preview_from_form(request: Request, limit: int = Query(20)):
    current_user = require_login(request)
    if not current_user:
        return JSONResponse({"error": "Non autenticato"}, status_code=401)
    payload: dict[str, Any] = {}
    try:
        payload = await request.json()
        source = build_source_from_payload(payload if isinstance(payload, dict) else {})
        src_type = str(source.get("type", "")).strip().lower()
        path = str(source.get("path") or source.get("config", {}).get("path") or "").strip()
        requires_path = src_type not in {"mysql", "gsheet_account"}
        if requires_path and not path:
            return JSONResponse({"error": "Percorso file obbligatorio per l'anteprima."}, status_code=400)
        if src_type == "gsheet_account":
            cfg = source.get("config") if isinstance(source.get("config"), dict) else {}
            connection_id = str(cfg.get("connection_id", "")).strip()
            spreadsheet_id = str(cfg.get("spreadsheet_id", "")).strip()
            if not connection_id:
                return JSONResponse({"error": "connection_id Google obbligatorio per l'anteprima."}, status_code=400)
            if not spreadsheet_id:
                return JSONResponse({"error": "spreadsheet_id Google obbligatorio per l'anteprima."}, status_code=400)
        df = load_dataframe_with_source_calculated_fields(source, use_fallback=True)
        source_calculated_fields = get_source_calculated_fields(source)
        calculated_fields = sanitize_calculated_fields(
            payload.get("calculated_fields", []) if isinstance(payload, dict) else []
        )
        if calculated_fields and calculated_fields != source_calculated_fields:
            df = apply_calculated_fields_to_dataframe(df, calculated_fields)
        return build_dataframe_preview_payload(source, df, limit=limit)
    except (ValueError, RuntimeError) as exc:
        logger.warning("source-preview/form validation error: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        source_id = str(payload.get("id", "")) if isinstance(payload, dict) else ""
        source_type = str(payload.get("type", "")) if isinstance(payload, dict) else ""
        logger.exception(
            "source-preview/form unexpected error (source_id=%s, source_type=%s): %s",
            source_id,
            source_type,
            exc,
        )
        return JSONResponse({"error": str(exc)}, status_code=500)

@app.get("/fields")
def fields(request: Request, source_id: str = Query(...), pivot_id: str | None = Query(None)):
    if not require_login(request):
        return JSONResponse({"error": "Non autenticato"}, status_code=401)
    try:
        _, df = load_source_df(source_id)
        df = apply_preset_calculated_fields(df, pivot_id=pivot_id, source_id=source_id)
        return {"fields": [str(c).strip() for c in df.columns]}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/pivots")
def pivots(source_id: str = Query(...)):
    try:
        items = load_pivot_files(source_id)
        return {"items": items}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/filter-values")
def filter_values(
    source_id: str = Query(...),
    field: str = Query(...),
    pivot_id: str | None = Query(None),
):
    try:
        _, df = load_source_df(source_id)
        df = apply_preset_calculated_fields(df, pivot_id=pivot_id, source_id=source_id)

        if field not in df.columns:
            return {"values": [], "field_type": "unknown"}

        if looks_like_date_field(field):
            values = format_filter_date_values(df[field])
            return {"values": values, "field_type": "date"}

        numeric_values = normalize_numeric_values(df[field])
        if numeric_values is not None:
            return {"values": numeric_values, "field_type": "number"}

        values = normalize_text_values(df[field])
        return {"values": values, "field_type": "text"}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/preset-editor/save")
async def preset_editor_save(request: Request):
    try:
        payload = await request.json()

        source_id = normalize_source_id(payload.get("source_id"))
        if not source_id:
            return JSONResponse({"error": "source_id obbligatorio"}, status_code=400)

        filename = sanitize_filename(payload.get("filename"))
        saved_filename, data = save_preset_file(source_id, filename, payload)

        return {
            "ok": True,
            "filename": saved_filename,
            "preset_id": data.get("id"),
            "preset": data,
        }
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/preset-editor/delete")
async def preset_editor_delete(request: Request):
    try:
        payload = await request.json()
        source_id = normalize_source_id(payload.get("source_id"))
        filename = payload.get("filename")
        preset_id = payload.get("preset_id")

        if not source_id:
            return JSONResponse({"error": "source_id obbligatorio"}, status_code=400)

        ok = delete_preset_file(source_id, filename=filename, preset_id=preset_id)
        if not ok:
            return JSONResponse({"error": "Preset non trovato"}, status_code=404)

        return {"ok": True}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


def _compute_pivot_result(
    pivot_id: str,
    source_id: str | None = None,
    filters: str | None = None,
    view_options: str | None = None,
) -> dict[str, Any]:
    sid = normalize_source_id(source_id)
    preset = find_preset_by_id(pivot_id, source_id=sid)

    if not preset:
        raise FileNotFoundError(f"Preset non trovato: {pivot_id}")

    sid = sid or preset.get("source_id")
    src, df = load_source_df(sid)
    df = apply_calculated_fields_to_dataframe(df, preset.get("calculated_fields", []))

    missing = validate_preset_columns(list(df.columns), preset)
    if missing:
        raise ValueError(
            json.dumps(
                {
                    "error": "Colonne mancanti nella sorgente per questo preset",
                    "missing_columns": missing,
                    "available_columns": list(df.columns),
                    "preset_id": preset.get("id"),
                    "preset_file": preset.get("_filename"),
                    "preset_options": preset.get("options", {}),
                },
                ensure_ascii=False,
            )
        )

    flt = json.loads(filters) if filters else {}
    runtime_view_options = json.loads(view_options) if view_options else {}

    preset = dict(preset)
    app_settings = load_settings_data()
    preset["options"] = {
        **(preset.get("options", {}) or {}),
        **(runtime_view_options or {}),
    }
    if "case_sensitive" not in preset["options"]:
        preset["options"]["case_sensitive"] = bool(app_settings.get("pivot_case_sensitive", False))

    df = normalize_df(
        df,
        numeric_fields=preset.get("numeric_fields", []),
        date_fields=preset.get("date_fields", []),
    )
    case_sensitive = bool(preset.get("options", {}).get("case_sensitive", False))
    df = apply_filters(df, flt, case_sensitive=case_sensitive)

    if df.empty:
        return {
            "source": src,
            "preset": preset,
            "preset_options": preset.get("options", {}),
            "table": None,
            "html": "<p>Nessun dato dopo i filtri o sorgente senza righe.</p>",
            "rows": 0,
        }

    table = run_pivot(df, preset)
    return {
        "source": src,
        "preset": preset,
        "preset_options": preset.get("options", {}),
        "table": table,
        "html": table_to_html(table),
        "rows": len(table),
    }


@app.get("/pivot/run")
def pivot_run(
    pivot_id: str = Query(...),
    source_id: str | None = None,
    filters: str | None = None,
    view_options: str | None = None,
):
    try:
        result = _compute_pivot_result(pivot_id=pivot_id, source_id=source_id, filters=filters, view_options=view_options)
        result.pop("table", None)
        return result
    except FileNotFoundError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except ValueError as exc:
        try:
            return JSONResponse(json.loads(str(exc)), status_code=400)
        except Exception:
            return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/pivot/export")
def pivot_export(
    request: Request,
    pivot_id: str = Query(...),
    source_id: str | None = None,
    filters: str | None = None,
    view_options: str | None = None,
    fmt: str = Query("csv"),
):
    if not require_login(request):
        return JSONResponse({"error": "Non autenticato"}, status_code=401)
    if not has_license_feature("print"):
        return JSONResponse({"error": "Esportazione pivot disponibile solo con licenza Pro/Full attiva."}, status_code=403)
    try:
        fmt_norm = str(fmt or "csv").strip().lower()
        if fmt_norm not in {"csv", "xlsx", "ods", "html"}:
            return JSONResponse({"error": "Formato non supportato. Usa: csv, xlsx, ods, html."}, status_code=400)

        result = _compute_pivot_result(pivot_id=pivot_id, source_id=source_id, filters=filters, view_options=view_options)
        table = result.get("table")
        if table is None:
            return JSONResponse({"error": "Nessun dato da esportare dopo l'applicazione dei filtri."}, status_code=400)
        if not isinstance(table, pd.DataFrame):
            return JSONResponse({"error": "Formato pivot non valido per esportazione."}, status_code=500)

        export_df = table.copy()
        safe_name = sanitize_filename((result.get("preset", {}) or {}).get("id", "pivot_export")).rsplit(".", 1)[0]

        if fmt_norm == "csv":
            data = export_df.to_csv(index=False).encode("utf-8-sig")
            headers = {"Content-Disposition": f'attachment; filename="{safe_name}.csv"'}
            return Response(content=data, media_type="text/csv; charset=utf-8", headers=headers)

        if fmt_norm == "html":
            title = str((result.get("preset", {}) or {}).get("title", safe_name)).strip() or safe_name
            html = (
                "<!doctype html><html><head><meta charset='utf-8'>"
                f"<title>{title}</title></head><body>"
                f"<h2>{title}</h2>{table_to_html(export_df)}</body></html>"
            )
            headers = {"Content-Disposition": f'attachment; filename="{safe_name}.html"'}
            return Response(content=html.encode("utf-8"), media_type="text/html; charset=utf-8", headers=headers)

        output = BytesIO()
        engine = "openpyxl" if fmt_norm == "xlsx" else "odf"
        export_df.to_excel(output, index=False, engine=engine)
        output.seek(0)
        media_type = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            if fmt_norm == "xlsx"
            else "application/vnd.oasis.opendocument.spreadsheet"
        )
        headers = {"Content-Disposition": f'attachment; filename="{safe_name}.{fmt_norm}"'}
        return StreamingResponse(output, media_type=media_type, headers=headers)
    except FileNotFoundError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)
    except ValueError as exc:
        try:
            return JSONResponse(json.loads(str(exc)), status_code=400)
        except Exception:
            return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": f"Errore esportazione pivot: {exc}"}, status_code=500)


@app.get("/pivot/drilldown")
def pivot_drilldown(
    pivot_id: str = Query(...),
    source_id: str | None = None,
    filters: str | None = None,
    row_filters: str | None = None,
    limit: int = Query(300, ge=1, le=2000),
):
    try:
        if not has_license_feature("drilldown"):
            return JSONResponse(
                {"error": "Funzione dettaglio disponibile solo nelle licenze a pagamento."},
                status_code=403,
            )
        sid = normalize_source_id(source_id)
        preset = find_preset_by_id(pivot_id, source_id=sid)
        if not preset:
            return JSONResponse({"error": f"Preset non trovato: {pivot_id}"}, status_code=404)

        sid = sid or preset.get("source_id")
        _, df = load_source_df(sid)
        df = apply_calculated_fields_to_dataframe(df, preset.get("calculated_fields", []))

        df = normalize_df(
            df,
            numeric_fields=preset.get("numeric_fields", []),
            date_fields=preset.get("date_fields", []),
        )

        global_filters = json.loads(filters) if filters else {}
        if not isinstance(global_filters, dict):
            global_filters = {}

        subtotal_filters = json.loads(row_filters) if row_filters else {}
        if not isinstance(subtotal_filters, dict):
            subtotal_filters = {}

        options = preset.get("options", {}) if isinstance(preset.get("options"), dict) else {}
        case_sensitive = bool(options.get("case_sensitive", load_settings_data().get("pivot_case_sensitive", False)))
        effective_filters = {**global_filters, **subtotal_filters}
        filtered = apply_filters(df, effective_filters, case_sensitive=case_sensitive)

        cols = [str(c) for c in filtered.columns]
        total_rows = len(filtered)
        rows_preview = filtered.head(limit).to_dict(orient="records")

        return {
            "ok": True,
            "pivot_id": pivot_id,
            "source_id": sid,
            "applied_filters": effective_filters,
            "columns": cols,
            "rows": rows_preview,
            "total_rows": total_rows,
            "returned_rows": len(rows_preview),
            "truncated": total_rows > limit,
        }
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
