from __future__ import annotations

import json
import csv
import os
import sys
import platform
import hashlib
import shutil
import subprocess
import uuid
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, Query, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse
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

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
DATA_DIR = BASE_DIR / "data"
PIVOTS_DIR = BASE_DIR / "pivots"

CONFIG_PATH = DATA_DIR / "config.json"
SETTINGS_PATH = DATA_DIR / "settings.json"
SOURCES_PATH = DATA_DIR / "sources.json"
USERS_PATH = DATA_DIR / "users.json"
LICENSE_SETTINGS_PATH = DATA_DIR / "license_settings.json"
BRANDING_DIR = DATA_DIR / "branding"
CUSTOMER_LOGO_PATH = BRANDING_DIR / "customer_logo.png"
CUSTOMER_LOGO_META_PATH = BRANDING_DIR / "customer_logo.json"

LICENSES_DIR = BASE_DIR / "licenses"
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
}

DEFAULT_SOURCES = {
    "default_source": "",
    "items": [],
}

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
}

DEFAULT_DEV_FEATURES = {
    "subtotals": True,
    "preview": True,
    "print": True,
    "backup_restore": True,
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
    return out


def save_settings_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = DEFAULT_SETTINGS.copy()
    data.update(payload or {})
    lang = str(data.get("language", "en")).strip().lower()
    if lang not in {"it", "en"}:
        lang = "en"
    data["language"] = lang
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

    # fallback: qualsiasi licenza non demo abilita backup/restore anche se il flag non è esplicito
    if feature_name == "backup_restore":
        status = str(ctx.get("license_status", "")).strip().lower()
        return status not in {"", "demo"}

    return False


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

    return normalized


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
    if not default_source and normalized_items:
        default_source = normalized_items[0]["id"]

    if default_source and not any(x["id"] == default_source for x in normalized_items):
        default_source = normalized_items[0]["id"] if normalized_items else ""

    return {
        "default_source": default_source,
        "items": normalized_items,
    }


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
    return next((x for x in data.get("items", []) if x["id"] == sid), None)


def load_source_df(source_id: str | None) -> tuple[dict[str, Any], pd.DataFrame]:
    src = get_source_by_id(source_id)
    if not src:
        raise FileNotFoundError(f"Sorgente non trovata: {source_id}")

    df = load_dataframe_from_source_with_fallback(src)

    if df is None:
        raise RuntimeError(f"Nessun dataframe restituito dal connector per la sorgente: {source_id}")

    if not isinstance(df, pd.DataFrame):
        raise RuntimeError(f"Il connector non ha restituito un DataFrame valido per: {source_id}")

    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return src, df.fillna("")


def load_dataframe_for_plugin(source: dict[str, Any]) -> pd.DataFrame:
    df = load_dataframe_from_source(source)

    if df is None:
        raise RuntimeError(
            f"Nessun dataframe restituito dal connector per la sorgente: {source.get('id', '(senza id)')}"
        )

    if not isinstance(df, pd.DataFrame):
        raise RuntimeError(
            f"Il connector non ha restituito un DataFrame valido per: {source.get('id', '(senza id)')}"
        )

    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df.fillna("")


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


def load_plugins_enabled_map() -> dict[str, bool]:
    plugins_cfg = BASE_DIR / "plugins.json"
    raw = read_json(plugins_cfg, {}) or {}
    enabled = raw.get("enabled", {}) if isinstance(raw, dict) else {}
    if not isinstance(enabled, dict):
        return {}
    return {str(k): bool(v) for k, v in enabled.items()}


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
    rows = df.fillna("").head(limit).astype(str).to_dict(orient="records")
    cfg = src.get("config", {}) if isinstance(src.get("config"), dict) else {}
    delimiter = src.get("delimiter") or cfg.get("delimiter") or ""
    encoding = src.get("encoding") or cfg.get("encoding") or ""
    sheet_name = src.get("sheet_name") or cfg.get("sheet_name") or cfg.get("sheet") or ""
    skip_rows = src.get("skip_rows")
    if skip_rows is None:
        skip_rows = cfg.get("skip_rows", 0)
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
    path = str(payload.get("path", "") or "").strip()
    delimiter = str(payload.get("delimiter", "") or "").strip()
    encoding = str(payload.get("encoding", "") or "").strip()
    sheet_name = str(payload.get("sheet_name", "") or "").strip()
    skip_rows = payload.get("skip_rows", 0)
    try:
        skip_rows = max(int(skip_rows or 0), 0)
    except Exception:
        skip_rows = 0
    source = {
        "id": normalize_source_id(payload.get("id") or "preview") or "preview",
        "title": str(payload.get("title") or payload.get("id") or "Anteprima sorgente").strip() or "Anteprima sorgente",
        "type": src_type,
        "path": path,
        "delimiter": delimiter,
        "encoding": encoding,
        "sheet_name": sheet_name,
        "skip_rows": skip_rows,
        "config": {
            "path": path,
            "delimiter": delimiter,
            "encoding": encoding,
            "sheet_name": sheet_name,
            "skip_rows": skip_rows,
        },
    }
    return normalize_source_item(source) or source

plugin_manager = PluginManager(
    BASE_DIR / "plugins",
    enabled_map=load_plugins_enabled_map(),
)

plugin_api = PluginAPI(
    get_source=get_source_by_id,
    load_dataframe_from_source=load_dataframe_for_plugin,
    get_sources_bundle=load_sources_data,
    get_runtime_paths=get_runtime_paths,
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


@app.get("/plugins")
def plugins_registry():
    return plugin_manager.get_frontend_registry()


@app.get("/plugins/status")
def plugins_status():
    return plugin_manager.get_status()


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
        path = str(payload.get("path", "")).strip()
        make_default = bool(payload.get("make_default", False))
        config = payload.get("config") if isinstance(payload.get("config"), dict) else {}

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

        if existing:
            existing.update(record)
        else:
            items.append(record)

        if make_default or not data.get("default_source"):
            data["default_source"] = src_id

        saved = save_sources_data(data)
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
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askopenfilename(
            title="Seleziona sorgente dati",
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


@app.post("/source-preview/form")
async def source_preview_from_form(request: Request, limit: int = Query(20)):
    current_user = require_login(request)
    if not current_user:
        return JSONResponse({"error": "Non autenticato"}, status_code=401)
    try:
        payload = await request.json()
        source = build_source_from_payload(payload if isinstance(payload, dict) else {})
        path = str(source.get("path") or source.get("config", {}).get("path") or "").strip()
        if not path:
            return JSONResponse({"error": "Percorso file obbligatorio per l'anteprima."}, status_code=400)
        df = load_dataframe_from_source_with_fallback(source)
        calculated_fields = sanitize_calculated_fields(
            payload.get("calculated_fields", []) if isinstance(payload, dict) else []
        )
        df = apply_calculated_fields_to_dataframe(df, calculated_fields)
        return build_dataframe_preview_payload(source, df, limit=limit)
    except Exception as exc:
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


@app.get("/pivot/run")
def pivot_run(
    pivot_id: str = Query(...),
    source_id: str | None = None,
    filters: str | None = None,
    view_options: str | None = None,
):
    try:
        sid = normalize_source_id(source_id)
        preset = find_preset_by_id(pivot_id, source_id=sid)

        if not preset:
            return JSONResponse({"error": f"Preset non trovato: {pivot_id}"}, status_code=404)

        sid = sid or preset.get("source_id")
        src, df = load_source_df(sid)

        df = apply_calculated_fields_to_dataframe(df, preset.get("calculated_fields", []))

        missing = validate_preset_columns(list(df.columns), preset)
        if missing:
            return JSONResponse(
                {
                    "error": "Colonne mancanti nella sorgente per questo preset",
                    "missing_columns": missing,
                    "available_columns": list(df.columns),
                    "preset_id": preset.get("id"),
                    "preset_file": preset.get("_filename"),
                    "preset_options": preset.get("options", {}),
                },
                status_code=400,
            )

        flt = json.loads(filters) if filters else {}
        runtime_view_options = json.loads(view_options) if view_options else {}

        preset = dict(preset)
        preset["options"] = {
            **(preset.get("options", {}) or {}),
            **(runtime_view_options or {}),
        }

        df = normalize_df(
            df,
            numeric_fields=preset.get("numeric_fields", []),
            date_fields=preset.get("date_fields", []),
        )

        df = apply_filters(df, flt)

        if df.empty:
            return {
                "source": src,
                "preset": preset,
                "preset_options": preset.get("options", {}),
                "html": "<p>Nessun dato dopo i filtri o sorgente senza righe.</p>",
                "rows": 0,
            }

        table = run_pivot(df, preset)

        return {
            "source": src,
            "preset": preset,
            "preset_options": preset.get("options", {}),
            "html": table_to_html(table),
            "rows": len(table),
        }

    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
