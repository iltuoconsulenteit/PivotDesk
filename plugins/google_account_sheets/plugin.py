from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from services.google_account_sheets import (
    list_spreadsheets,
    list_worksheets,
    poll_device_authorization,
    start_device_authorization,
)


class DeviceStartPayload(BaseModel):
    connection_id: str = Field(..., min_length=1)
    client_id: str = Field(..., min_length=5)
    client_secret: str = Field(..., min_length=5)


class DevicePollPayload(BaseModel):
    connection_id: str = Field(..., min_length=1)


class SourceSuggestionPayload(BaseModel):
    connection_id: str = Field(..., min_length=1)
    spreadsheet_id: str = Field(..., min_length=3)
    worksheet: str | None = None
    cell_range: str | None = None
    source_id: str = "gsheet_account_source"
    source_title: str = "Google Account Sheet"



def register(app, plugin_api, manifest):
    router = APIRouter(prefix="/plugin/google-account-sheets", tags=["plugins", "google_account_sheets"])

    @router.post("/device/start")
    def device_start(payload: DeviceStartPayload):
        try:
            data = start_device_authorization(payload.connection_id, payload.client_id, payload.client_secret)
            return {"ok": True, **data}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/device/poll")
    def device_poll(payload: DevicePollPayload):
        try:
            data = poll_device_authorization(payload.connection_id)
            return {"ok": True, **data}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/spreadsheets")
    def spreadsheets(connection_id: str = Query(...), page_size: int = Query(50, ge=1, le=200)):
        try:
            items = list_spreadsheets(connection_id, page_size=page_size)
            return {"ok": True, "items": items}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/worksheets")
    def worksheets(connection_id: str = Query(...), spreadsheet_id: str = Query(...)):
        try:
            items = list_worksheets(connection_id, spreadsheet_id)
            return {"ok": True, "items": items}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/source-suggestion")
    def source_suggestion(payload: SourceSuggestionPayload):
        cfg = {
            "connection_id": payload.connection_id.strip(),
            "spreadsheet_id": payload.spreadsheet_id.strip(),
            "worksheet": str(payload.worksheet or "").strip(),
            "range": str(payload.cell_range or "").strip(),
        }
        return {
            "ok": True,
            "source": {
                "id": payload.source_id.strip() or "gsheet_account_source",
                "title": payload.source_title.strip() or "Google Account Sheet",
                "type": "gsheet_account",
                "path": "",
                "config": cfg,
            },
        }

    app.include_router(router)

    return {
        "menu": manifest.frontend.get("menu", []),
        "panel": manifest.frontend.get("panel", {}),
    }
