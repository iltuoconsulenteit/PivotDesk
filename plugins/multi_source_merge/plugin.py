from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from plugins.calculated_fields.backend import apply_calculated_fields


class MergeSourceConfig(BaseModel):
    source_id: str
    column_map: dict[str, str] = Field(default_factory=dict)
    calculated_fields: list[dict[str, Any]] = Field(default_factory=list)
    source_tag: str | None = None


class MultiMergeRequest(BaseModel):
    sources: list[MergeSourceConfig]
    output_columns: list[str] = Field(default_factory=list)
    include_source_tag: bool = True
    limit: int = Field(default=1000, ge=1, le=20000)


def _apply_calc(df, defs: list[dict[str, Any]]):
    if not defs:
        return df
    rows = df.fillna("").to_dict(orient="records")
    out = apply_calculated_fields(rows, defs)
    import pandas as pd

    return pd.DataFrame(out)


def register(app, plugin_api, manifest):
    router = APIRouter(prefix="/plugin/multi-source-merge", tags=["plugins", "multi_source_merge"])

    @router.post("/build")
    def merge_sources(payload: MultiMergeRequest):
        if not plugin_api.get_source or not plugin_api.load_dataframe_from_source:
            raise HTTPException(status_code=500, detail="Plugin API incompleta")
        if not payload.sources:
            raise HTTPException(status_code=400, detail="sources obbligatorio")

        merged_rows: list[dict[str, Any]] = []
        discovered_targets: list[str] = []

        for src_cfg in payload.sources:
            source = plugin_api.get_source(src_cfg.source_id)
            df = plugin_api.load_dataframe_from_source(source)
            df = _apply_calc(df, src_cfg.calculated_fields)

            records = df.fillna("").to_dict(orient="records")
            for row in records:
                out = {}
                for target_col, src_col in (src_cfg.column_map or {}).items():
                    out[target_col] = row.get(src_col, "")
                    if target_col not in discovered_targets:
                        discovered_targets.append(target_col)
                if payload.include_source_tag:
                    out["_source"] = src_cfg.source_tag or src_cfg.source_id
                    if "_source" not in discovered_targets:
                        discovered_targets.append("_source")
                merged_rows.append(out)
                if len(merged_rows) >= payload.limit:
                    break
            if len(merged_rows) >= payload.limit:
                break

        output_columns = payload.output_columns or discovered_targets
        normalized_rows = []
        for row in merged_rows:
            normalized_rows.append({col: row.get(col, "") for col in output_columns})

        return {
            "ok": True,
            "plugin": "multi_source_merge",
            "columns": output_columns,
            "rows": normalized_rows,
            "row_count": len(normalized_rows),
            "truncated": len(merged_rows) >= payload.limit,
        }

    app.include_router(router)

    return {
        "menu": manifest.frontend.get("menu", []),
        "panel": manifest.frontend.get("panel", {}),
    }
