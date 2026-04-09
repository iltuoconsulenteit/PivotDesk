from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pandas as pd

from .base import BaseSourceAdapter


class GoogleDriveSourceAdapter(BaseSourceAdapter):
    def load_dataframe(self) -> pd.DataFrame:
        cfg = self._get_config()
        url = str(cfg.get("url") or cfg.get("path") or self.source.get("path") or "").strip()
        if not url:
            raise RuntimeError("URL Google Drive/Sheet non configurato")

        direct_url = _to_download_url(url)
        lower = direct_url.lower()

        if "format=csv" in lower or lower.endswith(".csv"):
            df = pd.read_csv(direct_url, dtype=str)
        elif "format=xlsx" in lower or lower.endswith(".xlsx"):
            df = pd.read_excel(direct_url, dtype=str)
        elif "format=ods" in lower or lower.endswith(".ods"):
            df = pd.read_excel(direct_url, dtype=str, engine="odf")
        else:
            # fallback CSV for Google Sheets export links
            df = pd.read_csv(direct_url, dtype=str)

        return self._normalize_df(df)


def _to_download_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    path = parsed.path or ""
    query = parse_qs(parsed.query or "")

    if "docs.google.com" in host and "/spreadsheets/" in path:
        parts = [p for p in path.split("/") if p]
        sheet_id = parts[2] if len(parts) >= 3 else ""
        if not sheet_id:
            return url
        gid = (query.get("gid") or ["0"])[0]
        fmt = (query.get("format") or ["csv"])[0]
        return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format={fmt}&gid={gid}"

    if "drive.google.com" in host:
        parts = [p for p in path.split("/") if p]
        file_id = ""
        if "file" in parts and "d" in parts:
            try:
                file_id = parts[parts.index("d") + 1]
            except Exception:
                file_id = ""
        if not file_id:
            file_id = (query.get("id") or [""])[0]
        if file_id:
            return f"https://drive.google.com/uc?export=download&id={file_id}"

    return url
