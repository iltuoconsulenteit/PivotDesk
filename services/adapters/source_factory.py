from __future__ import annotations

from typing import Any

from services.adapters.csv_adapter import CsvSourceAdapter
from services.adapters.excel_adapter import ExcelSourceAdapter
from services.adapters.http_json_adapter import HttpJsonSourceAdapter
from services.adapters.gdrive_adapter import GoogleDriveSourceAdapter
from services.adapters.mysql_adapter import MySqlSourceAdapter
from services.adapters.ods_adapter import OdsSourceAdapter


def build_source_adapter(source: dict[str, Any], connections: dict[str, Any] | None = None):
    source_type = str(source.get("type", "")).strip().lower()

    if source_type == "csv":
        return CsvSourceAdapter(source, connections)

    if source_type in {"xlsx", "excel"}:
        return ExcelSourceAdapter(source, connections)

    if source_type == "ods":
        return OdsSourceAdapter(source, connections)

    if source_type == "mysql":
        return MySqlSourceAdapter(source, connections)

    if source_type in {"http_json", "api", "rest"}:
        return HttpJsonSourceAdapter(source, connections)

    if source_type in {"gdrive", "google_drive", "google_sheet"}:
        return GoogleDriveSourceAdapter(source, connections)

    raise RuntimeError(f"Tipo sorgente non supportato: {source_type}")
