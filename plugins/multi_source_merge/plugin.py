from __future__ import annotations

import csv
import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from plugins.calculated_fields.backend import apply_calculated_fields
from services.config_loader import DATA_DIR, load_sources, save_sources


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


class MultiMergeSaveRequest(MultiMergeRequest):
    source_id: str = Field(..., min_length=2)
    source_title: str = Field(..., min_length=2)
    set_default: bool = False


def _apply_calc(df, defs: list[dict[str, Any]]):
    if not defs:
        return df
    rows = df.fillna("").to_dict(orient="records")
    out = apply_calculated_fields(rows, defs)
    import pandas as pd

    return pd.DataFrame(out)


def _sanitize_source_id(value: str) -> str:
    raw = str(value or "").strip()
    digits = re.sub(r"[^0-9]+", "", raw)
    return digits


def _resolve_numeric_source_id(bundle: dict[str, Any], requested: str) -> str:
    sources = bundle.get("sources") if isinstance(bundle.get("sources"), list) else []
    used_ids: set[int] = set()
    for src in sources:
        try:
            n = int(str(src.get("id", "")).strip())
            if n > 0:
                used_ids.add(n)
        except Exception:
            continue
    requested_digits = _sanitize_source_id(requested)
    if requested_digits:
        candidate = int(requested_digits)
        if candidate > 0 and candidate not in used_ids:
            return str(candidate)
    next_id = (max(used_ids) + 1) if used_ids else 1
    while next_id in used_ids:
        next_id += 1
    return str(next_id)


def _build_merge_result(plugin_api, payload: MultiMergeRequest) -> dict[str, Any]:
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
    normalized_rows = [{col: row.get(col, "") for col in output_columns} for row in merged_rows]
    return {
        "ok": True,
        "plugin": "multi_source_merge",
        "columns": output_columns,
        "rows": normalized_rows,
        "row_count": len(normalized_rows),
        "truncated": len(merged_rows) >= payload.limit,
    }


def register(app, plugin_api, manifest):
    router = APIRouter(prefix="/plugin/multi-source-merge", tags=["plugins", "multi_source_merge"])

    @router.post("/build")
    def merge_sources(payload: MultiMergeRequest):
        if not plugin_api.get_source or not plugin_api.load_dataframe_from_source:
            raise HTTPException(status_code=500, detail="Plugin API incompleta")
        return _build_merge_result(plugin_api, payload)

    @router.post("/build-and-save-source")
    def merge_and_save_source(payload: MultiMergeSaveRequest):
        if not plugin_api.get_source or not plugin_api.load_dataframe_from_source:
            raise HTTPException(status_code=500, detail="Plugin API incompleta")
        merged = _build_merge_result(plugin_api, payload)
        bundle = load_sources()
        source_id = _resolve_numeric_source_id(bundle, payload.source_id)
        source_title = str(payload.source_title or f"Merge {source_id}").strip() or f"Merge {source_id}"
        out_dir = DATA_DIR / "generated_sources"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"{source_id}.csv"
        columns = [str(c) for c in (merged.get("columns") or [])]
        rows = merged.get("rows") or []
        with out_file.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow({c: row.get(c, "") for c in columns})

        sources = bundle.get("sources") if isinstance(bundle.get("sources"), list) else []
        item = {
            "id": source_id,
            "title": source_title,
            "type": "csv",
            "path": str(out_file),
            "delimiter": ",",
            "encoding": "utf-8-sig",
            "options": {"generated_by": "multi_source_merge"},
        }
        replaced = False
        for idx, src in enumerate(sources):
            if str(src.get("id", "")).strip() == source_id:
                sources[idx] = item
                replaced = True
                break
        if not replaced:
            sources.append(item)
        bundle["sources"] = sources
        if payload.set_default:
            bundle["default_source"] = source_id
        save_sources(bundle)
        return {"ok": True, "source": item, "merge": merged}

    app.include_router(router)

    return {
        "menu": manifest.frontend.get("menu", []),
        "panel": manifest.frontend.get("panel", {}),
    }
