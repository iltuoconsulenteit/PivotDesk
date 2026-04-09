from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import pandas as pd

from .base import BaseSourceAdapter


class HttpJsonSourceAdapter(BaseSourceAdapter):
    """
    Adapter base per sorgenti remote HTTP/HTTPS con payload JSON.

    Config supportata:
    - url: endpoint remoto
    - method: GET | POST (default GET)
    - headers: dict opzionale
    - body: dict/list/string opzionale (usato su POST)
    - timeout_sec: timeout richiesta (default 15)
    - json_path: percorso semplificato nel payload (es. "data.items")
    """

    def load_dataframe(self) -> pd.DataFrame:
        cfg = self._get_config()
        url = str(cfg.get("url", "")).strip()
        if not url:
            raise RuntimeError("URL API non configurato")

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise RuntimeError("Lo schema URL deve essere http oppure https")

        method = str(cfg.get("method", "GET")).strip().upper() or "GET"
        if method not in {"GET", "POST"}:
            raise RuntimeError("Metodo HTTP non supportato (usa GET o POST)")

        timeout_sec = cfg.get("timeout_sec", 15)
        try:
            timeout = float(timeout_sec)
        except Exception:
            timeout = 15.0
        timeout = max(1.0, timeout)

        headers_raw = cfg.get("headers", {})
        headers = headers_raw if isinstance(headers_raw, dict) else {}
        request_headers = {str(k): str(v) for k, v in headers.items()}
        request_headers.setdefault("Accept", "application/json")

        body = None
        if method == "POST":
            body_value = cfg.get("body")
            if body_value is None:
                body = b""
            elif isinstance(body_value, (dict, list)):
                body = json.dumps(body_value, ensure_ascii=False).encode("utf-8")
                request_headers.setdefault("Content-Type", "application/json; charset=utf-8")
            else:
                body = str(body_value).encode("utf-8")

        req = Request(url=url, method=method, headers=request_headers, data=body)
        try:
            with urlopen(req, timeout=timeout) as resp:
                payload_bytes = resp.read()
        except Exception as exc:
            raise RuntimeError(f"Errore chiamata API remota: {exc}") from exc

        try:
            payload = json.loads(payload_bytes.decode("utf-8", "ignore"))
        except Exception as exc:
            raise RuntimeError(f"Risposta API non JSON valida: {exc}") from exc

        json_path = str(cfg.get("json_path", "")).strip()
        extracted = _extract_json_path(payload, json_path) if json_path else payload
        rows = _rows_from_payload(extracted)
        df = pd.DataFrame(rows)
        return self._normalize_df(df)


def _extract_json_path(payload: Any, path: str) -> Any:
    current = payload
    for part in [x.strip() for x in path.split(".") if x.strip()]:
        if isinstance(current, dict):
            current = current.get(part)
            continue
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except Exception:
                return None
            continue
        return None
    return current


def _rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []

    if isinstance(payload, list):
        if all(isinstance(x, dict) for x in payload):
            return [dict(x) for x in payload]
        return [{"value": x} for x in payload]

    if isinstance(payload, dict):
        for key in ("items", "data", "results", "rows"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                if all(isinstance(x, dict) for x in candidate):
                    return [dict(x) for x in candidate]
                return [{"value": x} for x in candidate]
        return [payload]

    return [{"value": payload}]
