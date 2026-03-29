from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any
from urllib import parse, request, error

from services.config_loader import DATA_DIR

PLUGIN_DIR = DATA_DIR / "plugins" / "google_account_sheets"
CONNECTIONS_DIR = PLUGIN_DIR / "connections"

GOOGLE_SCOPE = "https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/spreadsheets.readonly"
DEVICE_CODE_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def _normalize_connection_id(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9._-]+", "_", raw).strip("._-")
    return cleaned or "default"


def _connection_dir(connection_id: str) -> Path:
    cid = _normalize_connection_id(connection_id)
    out = CONNECTIONS_DIR / cid
    out.mkdir(parents=True, exist_ok=True)
    return out


def _read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return dict(default or {})
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else dict(default or {})
    except Exception:
        return dict(default or {})


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _http_post_form(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = parse.urlencode({k: "" if v is None else str(v) for k, v in payload.items()}).encode("utf-8")
    req = request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "ignore")
            return json.loads(raw or "{}")
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", "ignore") if hasattr(exc, "read") else str(exc)
        raise RuntimeError(f"HTTP {exc.code}: {details}") from exc
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc


def _http_get_json(url: str, token: str) -> dict[str, Any]:
    req = request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    try:
        with request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "ignore")
            return json.loads(raw or "{}")
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", "ignore") if hasattr(exc, "read") else str(exc)
        raise RuntimeError(f"HTTP {exc.code}: {details}") from exc
    except Exception as exc:
        raise RuntimeError(str(exc)) from exc


def _credentials_path(connection_id: str) -> Path:
    return _connection_dir(connection_id) / "client.json"


def _device_path(connection_id: str) -> Path:
    return _connection_dir(connection_id) / "device.json"


def _token_path(connection_id: str) -> Path:
    return _connection_dir(connection_id) / "token.json"


def save_client_credentials(connection_id: str, client_id: str, client_secret: str) -> dict[str, Any]:
    cid = _normalize_connection_id(connection_id)
    payload = {
        "connection_id": cid,
        "client_id": str(client_id or "").strip(),
        "client_secret": str(client_secret or "").strip(),
        "updated_at": int(time.time()),
    }
    if not payload["client_id"] or not payload["client_secret"]:
        raise RuntimeError("client_id e client_secret sono obbligatori")
    _write_json(_credentials_path(cid), payload)
    return payload


def start_device_authorization(connection_id: str, client_id: str, client_secret: str) -> dict[str, Any]:
    creds = save_client_credentials(connection_id, client_id, client_secret)
    data = _http_post_form(
        DEVICE_CODE_URL,
        {
            "client_id": creds["client_id"],
            "scope": GOOGLE_SCOPE,
        },
    )
    if not data.get("device_code"):
        raise RuntimeError(f"Risposta Google non valida: {data}")

    device_payload = {
        "connection_id": creds["connection_id"],
        "device_code": data.get("device_code", ""),
        "user_code": data.get("user_code", ""),
        "verification_url": data.get("verification_url") or data.get("verification_uri", ""),
        "verification_url_complete": data.get("verification_url_complete") or data.get("verification_uri_complete", ""),
        "expires_in": int(data.get("expires_in", 0) or 0),
        "interval": int(data.get("interval", 5) or 5),
        "created_at": int(time.time()),
    }
    _write_json(_device_path(creds["connection_id"]), device_payload)
    return device_payload


def poll_device_authorization(connection_id: str) -> dict[str, Any]:
    cid = _normalize_connection_id(connection_id)
    creds = _read_json(_credentials_path(cid), {})
    device = _read_json(_device_path(cid), {})
    if not creds.get("client_id") or not creds.get("client_secret"):
        raise RuntimeError("Credenziali OAuth mancanti. Avvia prima il flusso device.")
    if not device.get("device_code"):
        raise RuntimeError("device_code non presente. Avvia prima il flusso device.")

    try:
        token_data = _http_post_form(
            TOKEN_URL,
            {
                "client_id": creds["client_id"],
                "client_secret": creds["client_secret"],
                "device_code": device["device_code"],
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )
    except RuntimeError as exc:
        text = str(exc).lower()
        if "authorization_pending" in text:
            return {"ok": True, "status": "pending", "message": "Autorizzazione non ancora completata."}
        if "slow_down" in text:
            return {"ok": True, "status": "pending", "message": "Google richiede di rallentare il polling."}
        if "expired_token" in text:
            return {"ok": False, "status": "expired", "message": "Device code scaduto. Riavvia il flusso."}
        raise

    now_ts = int(time.time())
    out = {
        "connection_id": cid,
        "access_token": token_data.get("access_token", ""),
        "refresh_token": token_data.get("refresh_token", ""),
        "scope": token_data.get("scope", ""),
        "token_type": token_data.get("token_type", "Bearer"),
        "expires_in": int(token_data.get("expires_in", 0) or 0),
        "created_at": now_ts,
        "expires_at": now_ts + int(token_data.get("expires_in", 0) or 0),
    }
    if not out["access_token"]:
        raise RuntimeError(f"Token non valido: {token_data}")

    # Preserve existing refresh_token if Google omits it.
    old_token = _read_json(_token_path(cid), {})
    if not out["refresh_token"] and old_token.get("refresh_token"):
        out["refresh_token"] = old_token.get("refresh_token", "")

    _write_json(_token_path(cid), out)
    return {"ok": True, "status": "authorized", "scopes": out.get("scope", "")}


def _refresh_access_token(connection_id: str, token: dict[str, Any], creds: dict[str, Any]) -> dict[str, Any]:
    refresh_token = str(token.get("refresh_token", "")).strip()
    if not refresh_token:
        raise RuntimeError("refresh_token mancante: rieseguire autorizzazione account Google.")

    data = _http_post_form(
        TOKEN_URL,
        {
            "client_id": creds.get("client_id", ""),
            "client_secret": creds.get("client_secret", ""),
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    now_ts = int(time.time())
    updated = dict(token)
    updated["access_token"] = data.get("access_token", "")
    updated["expires_in"] = int(data.get("expires_in", 0) or 0)
    updated["expires_at"] = now_ts + updated["expires_in"]
    updated["created_at"] = now_ts
    if data.get("scope"):
        updated["scope"] = data.get("scope")
    _write_json(_token_path(connection_id), updated)
    return updated


def get_valid_access_token(connection_id: str) -> str:
    cid = _normalize_connection_id(connection_id)
    token = _read_json(_token_path(cid), {})
    creds = _read_json(_credentials_path(cid), {})
    access_token = str(token.get("access_token", "")).strip()
    if not access_token:
        raise RuntimeError("Token Google non presente. Completa prima l'autorizzazione account.")

    now_ts = int(time.time())
    expires_at = int(token.get("expires_at", 0) or 0)
    if expires_at and now_ts >= (expires_at - 30):
        token = _refresh_access_token(cid, token, creds)
        access_token = str(token.get("access_token", "")).strip()

    if not access_token:
        raise RuntimeError("Access token Google non valido.")
    return access_token


def list_spreadsheets(connection_id: str, page_size: int = 50) -> list[dict[str, Any]]:
    token = get_valid_access_token(connection_id)
    query = parse.urlencode(
        {
            "q": "mimeType='application/vnd.google-apps.spreadsheet' and trashed=false",
            "fields": "files(id,name,modifiedTime,owners(displayName,emailAddress)),nextPageToken",
            "pageSize": max(1, min(int(page_size or 50), 200)),
            "orderBy": "modifiedTime desc",
        }
    )
    url = f"https://www.googleapis.com/drive/v3/files?{query}"
    data = _http_get_json(url, token)
    items = data.get("files", []) if isinstance(data.get("files"), list) else []
    out: list[dict[str, Any]] = []
    for item in items:
        owners = item.get("owners") if isinstance(item.get("owners"), list) else []
        owner = owners[0] if owners else {}
        out.append(
            {
                "id": str(item.get("id", "")).strip(),
                "name": str(item.get("name", "")).strip(),
                "modified_time": str(item.get("modifiedTime", "")).strip(),
                "owner": str(owner.get("displayName") or owner.get("emailAddress") or "").strip(),
            }
        )
    return [x for x in out if x.get("id")]


def list_worksheets(connection_id: str, spreadsheet_id: str) -> list[dict[str, Any]]:
    sid = str(spreadsheet_id or "").strip()
    if not sid:
        raise RuntimeError("spreadsheet_id obbligatorio")
    token = get_valid_access_token(connection_id)
    fields = parse.quote("sheets(properties(sheetId,title,index,gridProperties(rowCount,columnCount)))", safe="=(),")
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{parse.quote(sid)}?fields={fields}"
    data = _http_get_json(url, token)
    sheets = data.get("sheets") if isinstance(data.get("sheets"), list) else []
    out: list[dict[str, Any]] = []
    for item in sheets:
        prop = item.get("properties") if isinstance(item.get("properties"), dict) else {}
        grid = prop.get("gridProperties") if isinstance(prop.get("gridProperties"), dict) else {}
        out.append(
            {
                "sheet_id": int(prop.get("sheetId", 0) or 0),
                "title": str(prop.get("title", "")).strip(),
                "index": int(prop.get("index", 0) or 0),
                "rows": int(grid.get("rowCount", 0) or 0),
                "cols": int(grid.get("columnCount", 0) or 0),
            }
        )
    return [x for x in out if x.get("title")]


def read_sheet_as_rows(
    connection_id: str,
    spreadsheet_id: str,
    worksheet: str | None = None,
    cell_range: str | None = None,
) -> list[list[str]]:
    sid = str(spreadsheet_id or "").strip()
    if not sid:
        raise RuntimeError("spreadsheet_id obbligatorio")

    ws = str(worksheet or "").strip()
    rng = str(cell_range or "").strip()
    ws_escaped = ws.replace("'", "''")
    if ws and rng:
        range_expr = f"'{ws_escaped}'!{rng}"
    elif ws:
        range_expr = f"'{ws_escaped}'"
    elif rng:
        range_expr = rng
    else:
        sheets = list_worksheets(connection_id, sid)
        first = sheets[0]["title"] if sheets else "Sheet1"
        range_expr = "'" + first.replace("'", "''") + "'"

    token = get_valid_access_token(connection_id)
    params = parse.urlencode({"majorDimension": "ROWS"})
    safe_chars = "!:$'"
    url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{parse.quote(sid)}/values/"
        f"{parse.quote(range_expr, safe=safe_chars)}?{params}"
    )
    data = _http_get_json(url, token)
    values = data.get("values") if isinstance(data.get("values"), list) else []
    out: list[list[str]] = []
    for row in values:
        if isinstance(row, list):
            out.append(["" if x is None else str(x) for x in row])
    return out
