from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.config_loader import load_sources, save_sources


class ImportAllSheetsPayload(BaseModel):
    source_id: str = Field(..., min_length=1)


def _next_numeric_id(sources: list[dict[str, Any]]) -> str:
    used: set[int] = set()
    for src in sources:
        try:
            sid = int(str(src.get("id", "")).strip())
            if sid > 0:
                used.add(sid)
        except Exception:
            continue
    nxt = (max(used) + 1) if used else 1
    while nxt in used:
        nxt += 1
    return str(nxt)


def register(app, plugin_api, manifest):
    router = APIRouter(prefix="/plugin/xlsx-sheet-import", tags=["plugins", "xlsx_sheet_import"])

    @router.post("/import-all")
    def import_all_sheets(payload: ImportAllSheetsPayload):
        if not plugin_api.get_source:
            raise HTTPException(status_code=500, detail="Plugin API incompleta")

        source = plugin_api.get_source(payload.source_id)
        stype = str(source.get("type", "")).strip().lower()
        if stype != "xlsx":
            raise HTTPException(status_code=400, detail="Seleziona una sorgente XLSX.")
        path = str(source.get("path") or source.get("config", {}).get("path") or "").strip()
        if not path:
            raise HTTPException(status_code=400, detail="Percorso XLSX mancante.")
        file_path = Path(path)
        if not file_path.exists():
            raise HTTPException(status_code=400, detail=f"File non trovato: {path}")

        try:
            sheet_names = [str(s).strip() for s in pd.ExcelFile(file_path).sheet_names if str(s).strip()]
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Impossibile leggere fogli XLSX: {exc}") from exc
        if not sheet_names:
            raise HTTPException(status_code=400, detail="Nessun foglio trovato nel file XLSX.")

        bundle = load_sources()
        sources = bundle.get("sources") if isinstance(bundle.get("sources"), list) else []

        basename = file_path.stem.strip() or "file"
        created: list[dict[str, Any]] = []
        updated: list[dict[str, Any]] = []
        for sheet in sheet_names:
            title = f"{basename}_{sheet}"
            existing = next(
                (
                    src
                    for src in sources
                    if str(src.get("type", "")).strip().lower() == "xlsx"
                    and str(src.get("path", "")).strip() == path
                    and str(src.get("sheet_name", src.get("config", {}).get("sheet_name", ""))).strip() == sheet
                ),
                None,
            )
            if existing is None:
                item = {
                    "id": _next_numeric_id(sources),
                    "title": title,
                    "type": "xlsx",
                    "path": path,
                    "sheet_name": sheet,
                    "skip_rows": 0,
                    "options": {"generated_by": "xlsx_sheet_import"},
                }
                sources.append(item)
                created.append(item)
            else:
                existing["title"] = title
                existing["sheet_name"] = sheet
                cfg = existing.get("config") if isinstance(existing.get("config"), dict) else {}
                cfg["sheet_name"] = sheet
                existing["config"] = cfg
                updated.append(existing)

        bundle["sources"] = sources
        save_sources(bundle)
        return {
            "ok": True,
            "source_file": path,
            "sheet_count": len(sheet_names),
            "created_count": len(created),
            "updated_count": len(updated),
            "created": [{"id": x.get("id"), "title": x.get("title"), "sheet_name": x.get("sheet_name")} for x in created],
            "updated": [{"id": x.get("id"), "title": x.get("title"), "sheet_name": x.get("sheet_name")} for x in updated],
        }

    app.include_router(router)
    return {
        "menu": manifest.frontend.get("menu", []),
        "panel": manifest.frontend.get("panel", {}),
    }
