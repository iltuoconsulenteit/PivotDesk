from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from plugins.calculated_fields.backend import apply_calculated_fields


class CrossLookupRequest(BaseModel):
    primary_source_id: str
    secondary_source_id: str
    primary_match_field: str
    secondary_match_field: str
    secondary_pick_fields: list[str] = Field(default_factory=list)
    primary_calculated_fields: list[dict[str, Any]] = Field(default_factory=list)
    secondary_calculated_fields: list[dict[str, Any]] = Field(default_factory=list)
    result_prefix: str = "lk_"
    match_mode: str = "exact"  # exact | contains
    group_by_fields: list[str] = Field(default_factory=list)
    aggregate_field: str | None = None
    aggregate_fn: str = "sum"  # sum | count | avg
    limit: int = Field(default=300, ge=1, le=5000)


def _apply_calc(df, defs: list[dict[str, Any]]):
    if not defs:
        return df
    rows = df.fillna("").to_dict(orient="records")
    out = apply_calculated_fields(rows, defs)
    import pandas as pd

    return pd.DataFrame(out)


def register(app, plugin_api, manifest):
    router = APIRouter(prefix="/plugin/cross-source-lookup", tags=["plugins", "cross_source_lookup"])

    @router.post("/query")
    def cross_lookup(payload: CrossLookupRequest):
        if not plugin_api.get_source or not plugin_api.load_dataframe_from_source:
            raise HTTPException(status_code=500, detail="Plugin API incompleta")

        primary_src = plugin_api.get_source(payload.primary_source_id)
        secondary_src = plugin_api.get_source(payload.secondary_source_id)
        primary_df = plugin_api.load_dataframe_from_source(primary_src)
        secondary_df = plugin_api.load_dataframe_from_source(secondary_src)

        primary_df = _apply_calc(primary_df, payload.primary_calculated_fields)
        secondary_df = _apply_calc(secondary_df, payload.secondary_calculated_fields)

        for required, df in [
            (payload.primary_match_field, primary_df),
            (payload.secondary_match_field, secondary_df),
        ]:
            if required not in df.columns:
                raise HTTPException(status_code=400, detail=f"Campo mancante: {required}")

        pick_fields = [f for f in payload.secondary_pick_fields if f in secondary_df.columns]
        if not pick_fields:
            pick_fields = [c for c in secondary_df.columns if c != payload.secondary_match_field][:4]

        index_rows = {}
        for row in secondary_df.fillna("").to_dict(orient="records"):
            key = str(row.get(payload.secondary_match_field, "")).strip().lower()
            if not key:
                continue
            index_rows.setdefault(key, row)

        out_rows: list[dict[str, Any]] = []
        contains_mode = str(payload.match_mode or "exact").strip().lower() == "contains"

        for row in primary_df.fillna("").to_dict(orient="records"):
            left_key = str(row.get(payload.primary_match_field, "")).strip().lower()
            matched = None
            if left_key:
                if contains_mode:
                    for idx_key, idx_row in index_rows.items():
                        if left_key in idx_key or idx_key in left_key:
                            matched = idx_row
                            break
                else:
                    matched = index_rows.get(left_key)

            enriched = dict(row)
            for f in pick_fields:
                enriched[f"{payload.result_prefix}{f}"] = "" if not matched else matched.get(f, "")
            enriched[f"{payload.result_prefix}match_found"] = bool(matched)
            out_rows.append(enriched)

        out_rows = out_rows[: payload.limit]

        grouped = []
        if payload.group_by_fields:
            import pandas as pd

            gdf = pd.DataFrame(out_rows)
            group_fields = [f for f in payload.group_by_fields if f in gdf.columns]
            if group_fields:
                agg_fn = str(payload.aggregate_fn or "sum").strip().lower()
                if agg_fn == "count" or not payload.aggregate_field or payload.aggregate_field not in gdf.columns:
                    grouped_df = gdf.groupby(group_fields, dropna=False).size().reset_index(name="count")
                else:
                    num = pd.to_numeric(gdf[payload.aggregate_field], errors="coerce").fillna(0)
                    gdf = gdf.assign(_agg_num=num)
                    if agg_fn == "avg":
                        grouped_df = gdf.groupby(group_fields, dropna=False)["_agg_num"].mean().reset_index(name="avg")
                    else:
                        grouped_df = gdf.groupby(group_fields, dropna=False)["_agg_num"].sum().reset_index(name="sum")
                grouped = grouped_df.fillna("").to_dict(orient="records")

        return {
            "ok": True,
            "plugin": "cross_source_lookup",
            "primary_source_id": payload.primary_source_id,
            "secondary_source_id": payload.secondary_source_id,
            "picked_fields": pick_fields,
            "rows": out_rows,
            "grouped": grouped,
        }

    app.include_router(router)

    return {
        "menu": manifest.frontend.get("menu", []),
        "panel": manifest.frontend.get("panel", {}),
    }
