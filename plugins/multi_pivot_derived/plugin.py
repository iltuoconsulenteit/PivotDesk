from __future__ import annotations

import json
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field


class PivotInput(BaseModel):
    pivot_id: str
    source_id: str | None = None
    alias: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)


class MultiPivotDerivedRequest(BaseModel):
    pivots: list[PivotInput]
    mode: str = "union"  # union | join
    join_on: list[str] = Field(default_factory=list)
    include_pivot_tag: bool = True
    limit: int = Field(default=2000, ge=1, le=20000)


_DEMO_WATERMARK_NOTE = "DEMO FULL - output con filigrana (non idoneo a stampa/export operativo)"


def _to_rows(df: pd.DataFrame, alias: str, include_tag: bool) -> list[dict[str, Any]]:
    rows = df.fillna("").to_dict(orient="records")
    out: list[dict[str, Any]] = []
    for row in rows:
        item = {str(k): row.get(k, "") for k in df.columns}
        if include_tag:
            item["_pivot"] = alias
        out.append(item)
    return out


def _apply_demo_watermark(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, row in enumerate(rows, start=1):
        item: dict[str, Any] = {}
        for k, v in row.items():
            if isinstance(v, str):
                item[k] = f"{v} · DEMO" if v else "DEMO"
            else:
                item[k] = v
        item["_watermark"] = f"DEMO_ROW_{i:05d}"
        out.append(item)
    return out


def register(app, plugin_api, manifest):
    router = APIRouter(prefix="/plugin/multi-pivot-derived", tags=["plugins", "multi_pivot_derived"])

    @router.post("/build")
    def build(payload: MultiPivotDerivedRequest):
        if not getattr(plugin_api, "compute_pivot_result", None):
            raise HTTPException(status_code=500, detail="Plugin API incompleta: compute_pivot_result non disponibile")

        if not payload.pivots:
            raise HTTPException(status_code=400, detail="pivots obbligatorio")

        ctx = plugin_api.get_license_context(prefer_online=False) if getattr(plugin_api, "get_license_context", None) else {}
        license_status = str((ctx or {}).get("license_status", "demo")).strip().lower() or "demo"
        license_is_dev = bool((ctx or {}).get("license_is_dev"))
        demo_watermark = (license_status == "demo") and (not license_is_dev)

        tables: list[tuple[str, pd.DataFrame]] = []
        for idx, p in enumerate(payload.pivots, start=1):
            alias = str(p.alias or p.pivot_id or f"pivot_{idx}").strip() or f"pivot_{idx}"
            try:
                result = plugin_api.compute_pivot_result(
                    pivot_id=p.pivot_id,
                    source_id=p.source_id,
                    filters=json.dumps(p.filters or {}, ensure_ascii=False),
                    view_options=None,
                )
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Errore pivot {p.pivot_id}: {exc}") from exc

            table = result.get("table") if isinstance(result, dict) else None
            if table is None or not isinstance(table, pd.DataFrame) or table.empty:
                continue

            df = table.copy()
            df.columns = [str(c).strip() for c in df.columns]
            tables.append((alias, df))

        if not tables:
            return {
                "ok": True,
                "rows": [],
                "columns": [],
                "mode": payload.mode,
                "watermarked_demo": demo_watermark,
                "watermark_note": _DEMO_WATERMARK_NOTE if demo_watermark else "",
            }

        mode = str(payload.mode or "union").strip().lower()
        rows: list[dict[str, Any]] = []

        if mode == "join":
            join_keys = [str(x).strip() for x in payload.join_on if str(x).strip()]
            if not join_keys:
                raise HTTPException(status_code=400, detail="join_on obbligatorio in modalità join")

            base_alias, base_df = tables[0]
            merged = base_df.copy()
            if payload.include_pivot_tag:
                merged["_pivot"] = base_alias

            for alias, next_df in tables[1:]:
                suffix = f"_{alias}"
                merged = merged.merge(next_df, on=join_keys, how="outer", suffixes=("", suffix))
                if payload.include_pivot_tag and "_pivot" in merged.columns:
                    merged["_pivot"] = merged["_pivot"].astype(str).replace("", base_alias)

            rows = merged.fillna("").to_dict(orient="records")
        else:
            for alias, df in tables:
                rows.extend(_to_rows(df, alias=alias, include_tag=payload.include_pivot_tag))

        rows = rows[: payload.limit]

        if demo_watermark:
            rows = _apply_demo_watermark(rows)

        cols = list(rows[0].keys()) if rows else []
        return {
            "ok": True,
            "plugin": "multi_pivot_derived",
            "mode": mode,
            "input_pivots": [p.pivot_id for p in payload.pivots],
            "join_on": payload.join_on,
            "rows": rows,
            "columns": cols,
            "watermarked_demo": demo_watermark,
            "watermark_note": _DEMO_WATERMARK_NOTE if demo_watermark else "",
            "developer_full_access": license_is_dev,
            "license_status": license_status,
        }

    app.include_router(router)

    return {
        "menu": manifest.frontend.get("menu", []),
        "panel": manifest.frontend.get("panel", {}),
    }
