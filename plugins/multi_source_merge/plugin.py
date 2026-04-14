from __future__ import annotations

import csv
import json
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Response
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


class MergeTemplateHeadersRequest(BaseModel):
    source_id: str | None = None
    file_path: str | None = None
    file_type: str | None = None
    delimiter: str = ","
    encoding: str = "utf-8-sig"
    sheet_name: str | int | None = 0
    limit: int = Field(default=500, ge=1, le=5000)


class MergeMapSuggestionRequest(BaseModel):
    source_id: str
    template_columns: list[str] = Field(default_factory=list)
    calculated_fields: list[dict[str, Any]] = Field(default_factory=list)


class MergeTemplateCreateRequest(BaseModel):
    template_id: str | None = None
    title: str = Field(..., min_length=2)
    columns: list[str] = Field(default_factory=list)
    sources: list[MergeSourceConfig] = Field(default_factory=list)
    include_source_tag: bool = True
    overwrite: bool = False


class MergeTemplateBuildRequest(BaseModel):
    template_id: str = Field(..., min_length=2)
    sources: list[MergeSourceConfig] = Field(default_factory=list)
    include_source_tag: bool | None = None
    limit: int = Field(default=1000, ge=1, le=20000)


class MergeExportCsvRequest(MultiMergeRequest):
    filename: str | None = None


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


def _normalize_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _load_headers_from_file(payload: MergeTemplateHeadersRequest) -> list[str]:
    path = str(payload.file_path or "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="file_path obbligatorio")
    file_type = str(payload.file_type or "").strip().lower()
    if not file_type:
        low = path.lower()
        if low.endswith(".csv"):
            file_type = "csv"
        elif low.endswith(".xlsx") or low.endswith(".xlsm") or low.endswith(".xls"):
            file_type = "excel"
        elif low.endswith(".ods"):
            file_type = "ods"

    if file_type == "csv":
        with open(path, "r", encoding=payload.encoding, newline="") as f:
            reader = csv.reader(f, delimiter=payload.delimiter or ",")
            first = next(reader, [])
            return [str(v).strip() for v in first if str(v).strip()][: payload.limit]

    if file_type in {"excel", "xlsx", "xls", "ods"}:
        import pandas as pd

        df = pd.read_excel(path, sheet_name=payload.sheet_name, nrows=0)
        return [str(c).strip() for c in list(df.columns) if str(c).strip()][: payload.limit]

    raise HTTPException(status_code=400, detail="file_type non supportato (usa csv/excel/ods)")


def _build_map_suggestions(df_columns: list[str], template_columns: list[str]) -> dict[str, str]:
    source_by_norm: dict[str, str] = {}
    for src_col in df_columns:
        norm = _normalize_label(src_col)
        if norm and norm not in source_by_norm:
            source_by_norm[norm] = src_col

    out: dict[str, str] = {}
    for target in template_columns:
        norm = _normalize_label(target)
        if not norm:
            continue
        if norm in source_by_norm:
            out[target] = source_by_norm[norm]
            continue
        for src_norm, src_col in source_by_norm.items():
            if norm in src_norm or src_norm in norm:
                out[target] = src_col
                break
    return out


def _json_safe_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    try:
        # pandas / numpy nullable values
        if value != value:  # NaN
            return ""
    except Exception:
        pass
    return str(value)


def _normalize_template_id(value: str) -> str:
    return _sanitize_source_id(value)


def _templates_path() -> Path:
    return DATA_DIR / "merge_templates.json"


def _templates_db_path() -> Path:
    app_data_dir = DATA_DIR / "app_data"
    app_data_dir.mkdir(parents=True, exist_ok=True)
    return app_data_dir / "merge_templates.db"


def _db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_templates_db_path()))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS merge_templates (
            template_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            columns_json TEXT NOT NULL,
            sources_json TEXT NOT NULL,
            include_source_tag INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    return conn


def _migrate_templates_json_to_sqlite() -> None:
    legacy = _templates_path()
    if not legacy.exists():
        return
    try:
        raw = json.loads(legacy.read_text(encoding="utf-8"))
        legacy_items = raw.get("templates", []) if isinstance(raw, dict) else []
    except Exception:
        return
    if not isinstance(legacy_items, list) or not legacy_items:
        return

    conn = _db_connect()
    cur = conn.cursor()
    count_row = cur.execute("SELECT COUNT(1) FROM merge_templates").fetchone()
    existing_count = int(count_row[0] or 0) if count_row else 0
    if existing_count > 0:
        conn.close()
        return

    for row in legacy_items:
        if not isinstance(row, dict):
            continue
        template_id = str(row.get("template_id", "")).strip()
        if not template_id:
            continue
        title = str(row.get("title") or template_id).strip() or template_id
        columns = [str(c).strip() for c in (row.get("columns") or []) if str(c).strip()]
        sources = row.get("sources") if isinstance(row.get("sources"), list) else []
        include_source_tag = 1 if bool(row.get("include_source_tag", True)) else 0
        cur.execute(
            """
            INSERT OR REPLACE INTO merge_templates
            (template_id, title, columns_json, sources_json, include_source_tag, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                template_id,
                title,
                json.dumps(columns, ensure_ascii=False),
                json.dumps(sources, ensure_ascii=False),
                include_source_tag,
            ),
        )
    conn.commit()
    conn.close()


def _load_templates() -> list[dict[str, Any]]:
    _migrate_templates_json_to_sqlite()
    conn = _db_connect()
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT template_id, title, columns_json, sources_json, include_source_tag
        FROM merge_templates
        ORDER BY updated_at DESC, template_id DESC
        """
    ).fetchall()
    conn.close()

    out: list[dict[str, Any]] = []
    for template_id, title, columns_json, sources_json, include_source_tag in rows:
        try:
            columns = json.loads(columns_json) if str(columns_json or "").strip() else []
            if not isinstance(columns, list):
                columns = []
        except Exception:
            columns = []
        try:
            sources = json.loads(sources_json) if str(sources_json or "").strip() else []
            if not isinstance(sources, list):
                sources = []
        except Exception:
            sources = []
        out.append(
            {
                "template_id": str(template_id or "").strip(),
                "title": str(title or "").strip(),
                "columns": [str(c).strip() for c in columns if str(c).strip()],
                "sources": [x for x in sources if isinstance(x, dict)],
                "include_source_tag": bool(include_source_tag),
            }
        )
    return [x for x in out if x.get("template_id")]


def _save_templates(items: list[dict[str, Any]]) -> None:
    conn = _db_connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM merge_templates")
    for row in items:
        if not isinstance(row, dict):
            continue
        template_id = str(row.get("template_id", "")).strip()
        if not template_id:
            continue
        title = str(row.get("title") or template_id).strip() or template_id
        columns = [str(c).strip() for c in (row.get("columns") or []) if str(c).strip()]
        sources = row.get("sources") if isinstance(row.get("sources"), list) else []
        include_source_tag = 1 if bool(row.get("include_source_tag", True)) else 0
        cur.execute(
            """
            INSERT INTO merge_templates
            (template_id, title, columns_json, sources_json, include_source_tag, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                template_id,
                title,
                json.dumps(columns, ensure_ascii=False),
                json.dumps(sources, ensure_ascii=False),
                include_source_tag,
            ),
        )
    conn.commit()
    conn.close()


def _find_template(items: list[dict[str, Any]], template_id: str) -> dict[str, Any] | None:
    wanted = str(template_id or "").strip()
    for item in items:
        if str(item.get("template_id", "")).strip() == wanted:
            return item
    return None


def _resolve_numeric_template_id(items: list[dict[str, Any]], requested: str | None, overwrite: bool) -> str:
    used_ids: set[int] = set()
    for row in items:
        try:
            n = int(str(row.get("template_id", "")).strip())
            if n > 0:
                used_ids.add(n)
        except Exception:
            continue
    wanted = _normalize_template_id(str(requested or ""))
    if wanted:
        candidate = int(wanted)
        if candidate > 0 and (candidate not in used_ids or overwrite):
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
        try:
            source = plugin_api.get_source(src_cfg.source_id)
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Sorgente non trovata nel merge: {src_cfg.source_id} ({exc})",
            ) from exc
        try:
            df = plugin_api.load_dataframe_from_source(source)
            df = _apply_calc(df, src_cfg.calculated_fields)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Errore lettura sorgente merge {src_cfg.source_id}: {exc}",
            ) from exc

        try:
            records = df.fillna("").to_dict(orient="records")
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Formato dati non valido per sorgente {src_cfg.source_id}: {exc}",
            ) from exc
        for row in records:
            out = {}
            for target_col, src_col in (src_cfg.column_map or {}).items():
                out[target_col] = _json_safe_value(row.get(src_col, ""))
                if target_col not in discovered_targets:
                    discovered_targets.append(target_col)
            if payload.include_source_tag:
                out["_source"] = _json_safe_value(src_cfg.source_tag or src_cfg.source_id)
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


def _merge_result_to_csv_bytes(merge_result: dict[str, Any]) -> bytes:
    columns = [str(c) for c in (merge_result.get("columns") or [])]
    rows = merge_result.get("rows") if isinstance(merge_result, dict) else []
    safe_rows = rows if isinstance(rows, list) else []
    from io import StringIO

    out = StringIO()
    writer = csv.DictWriter(out, fieldnames=columns)
    writer.writeheader()
    for row in safe_rows:
        row_data = row if isinstance(row, dict) else {}
        writer.writerow({c: row_data.get(c, "") for c in columns})
    return out.getvalue().encode("utf-8-sig")


def _plugin_license_allowed(plugin_api, plugin_id: str = "multi_source_merge") -> bool:
    ctx = plugin_api.get_license_context(prefer_online=False) if getattr(plugin_api, "get_license_context", None) else {}
    features = ctx.get("license_features", {}) if isinstance(ctx, dict) and isinstance(ctx.get("license_features"), dict) else {}
    if features.get("*") is True:
        return True
    if bool(ctx.get("license_is_dev")):
        return True
    pid = str(plugin_id or "").strip().lower()
    if not pid:
        return False
    if bool(features.get("plugins")):
        return True
    candidates = [pid, f"plugin_{pid}", f"plugins.{pid}", f"plugins:{pid}"]
    return any(bool(features.get(name)) for name in candidates)


def register(app, plugin_api, manifest):
    router = APIRouter(prefix="/plugin/multi-source-merge", tags=["plugins", "multi_source_merge"])

    def ensure_plugin_allowed() -> None:
        if not _plugin_license_allowed(plugin_api, "multi_source_merge"):
            raise HTTPException(status_code=403, detail="Plugin Multi Source Merge non abilitato dalla licenza.")

    @router.post("/build")
    def merge_sources(payload: MultiMergeRequest):
        ensure_plugin_allowed()
        if not plugin_api.get_source or not plugin_api.load_dataframe_from_source:
            raise HTTPException(status_code=500, detail="Plugin API incompleta")
        try:
            return _build_merge_result(plugin_api, payload)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Errore merge: {exc}") from exc

    @router.post("/export-csv")
    def export_merge_csv(payload: MergeExportCsvRequest):
        ensure_plugin_allowed()
        if not plugin_api.get_source or not plugin_api.load_dataframe_from_source:
            raise HTTPException(status_code=500, detail="Plugin API incompleta")
        try:
            merged = _build_merge_result(plugin_api, payload)
            csv_bytes = _merge_result_to_csv_bytes(merged)
            suggested = str(payload.filename or f"merge_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv").strip()
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", suggested) or "merge_export.csv"
            if not safe.lower().endswith(".csv"):
                safe += ".csv"
            headers = {"Content-Disposition": f'attachment; filename=\"{safe}\"'}
            return Response(content=csv_bytes, media_type="text/csv; charset=utf-8", headers=headers)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Errore export CSV merge: {exc}") from exc

    @router.post("/template/headers")
    def resolve_template_headers(payload: MergeTemplateHeadersRequest):
        ensure_plugin_allowed()
        if payload.source_id:
            try:
                source = plugin_api.get_source(payload.source_id)
                df = plugin_api.load_dataframe_from_source(source)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Errore lettura sorgente {payload.source_id}: {exc}") from exc
            headers = [str(c).strip() for c in list(df.columns) if str(c).strip()][: payload.limit]
            return {"ok": True, "mode": "source", "headers": headers, "count": len(headers)}

        headers = _load_headers_from_file(payload)
        return {"ok": True, "mode": "file", "headers": headers, "count": len(headers)}

    @router.post("/template/suggest-map")
    def suggest_map(payload: MergeMapSuggestionRequest):
        ensure_plugin_allowed()
        if not plugin_api.get_source or not plugin_api.load_dataframe_from_source:
            raise HTTPException(status_code=500, detail="Plugin API incompleta")
        try:
            source = plugin_api.get_source(payload.source_id)
            df = plugin_api.load_dataframe_from_source(source)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Errore lettura sorgente {payload.source_id}: {exc}") from exc
        df = _apply_calc(df, payload.calculated_fields)
        source_columns = [str(c).strip() for c in list(df.columns) if str(c).strip()]
        suggestions = _build_map_suggestions(source_columns, payload.template_columns)
        return {
            "ok": True,
            "source_id": payload.source_id,
            "source_columns": source_columns,
            "template_columns": payload.template_columns,
            "suggestions": suggestions,
        }

    @router.get("/template/list")
    def list_templates():
        ensure_plugin_allowed()
        items = _load_templates()
        return {"ok": True, "templates": items, "count": len(items)}

    @router.get("/template/{template_id}")
    def get_template(template_id: str):
        ensure_plugin_allowed()
        items = _load_templates()
        found = _find_template(items, template_id)
        if not found:
            raise HTTPException(status_code=404, detail="template non trovato")
        return {"ok": True, "template": found}

    @router.post("/template/save")
    def save_template(payload: MergeTemplateCreateRequest):
        ensure_plugin_allowed()
        items = _load_templates()
        template_id = _resolve_numeric_template_id(items, payload.template_id, payload.overwrite)
        columns = [str(c).strip() for c in payload.columns if str(c).strip()]
        if not columns:
            raise HTTPException(status_code=400, detail="columns obbligatorio")
        saved_sources: list[dict[str, Any]] = []
        for src_cfg in payload.sources or []:
            src_id = str(src_cfg.source_id or "").strip()
            if not src_id:
                continue
            col_map = {
                str(k).strip(): str(v).strip()
                for k, v in (src_cfg.column_map or {}).items()
                if str(k).strip() and str(v).strip()
            }
            saved_sources.append(
                {
                    "source_id": src_id,
                    "column_map": col_map,
                    "calculated_fields": src_cfg.calculated_fields or [],
                    "source_tag": src_cfg.source_tag,
                }
            )
        item = {
            "template_id": template_id,
            "title": str(payload.title or template_id).strip(),
            "columns": columns,
            "sources": saved_sources,
            "include_source_tag": bool(payload.include_source_tag),
        }
        existing_idx = -1
        for idx, row in enumerate(items):
            if str(row.get("template_id", "")).strip() == template_id:
                existing_idx = idx
                break
        if existing_idx >= 0 and not payload.overwrite:
            raise HTTPException(status_code=409, detail="template già esistente (usa overwrite=true)")
        if existing_idx >= 0:
            items[existing_idx] = item
        else:
            items.append(item)
        _save_templates(items)
        return {"ok": True, "template": item}

    @router.delete("/template/{template_id}")
    def delete_template(template_id: str):
        ensure_plugin_allowed()
        items = _load_templates()
        before = len(items)
        items = [i for i in items if str(i.get("template_id", "")).strip() != str(template_id or "").strip()]
        if len(items) == before:
            raise HTTPException(status_code=404, detail="template non trovato")
        _save_templates(items)
        return {"ok": True, "deleted": template_id}

    @router.post("/build-from-template")
    def build_from_template(payload: MergeTemplateBuildRequest):
        ensure_plugin_allowed()
        try:
            items = _load_templates()
            tpl = _find_template(items, payload.template_id)
            if not tpl:
                raise HTTPException(status_code=404, detail="template non trovato")
            sources_payload = payload.sources
            if not sources_payload:
                fallback = tpl.get("sources") if isinstance(tpl, dict) else []
                sources_payload = [MergeSourceConfig(**row) for row in (fallback or []) if isinstance(row, dict)]
            if not sources_payload:
                raise HTTPException(status_code=400, detail="sources obbligatorio")
            req = MultiMergeRequest(
                sources=sources_payload,
                output_columns=[str(c) for c in (tpl.get("columns") or []) if str(c).strip()],
                include_source_tag=(
                    bool(payload.include_source_tag)
                    if payload.include_source_tag is not None
                    else bool(tpl.get("include_source_tag", True))
                ),
                limit=payload.limit,
            )
            result = _build_merge_result(plugin_api, req)
            result["template_id"] = payload.template_id
            result["template"] = tpl
            return result
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Errore build da template: {exc}") from exc

    @router.post("/build-and-save-source")
    def merge_and_save_source(payload: MultiMergeSaveRequest):
        ensure_plugin_allowed()
        if not plugin_api.get_source or not plugin_api.load_dataframe_from_source:
            raise HTTPException(status_code=500, detail="Plugin API incompleta")
        try:
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
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Errore salvataggio sorgente merge: {exc}") from exc

    app.include_router(router)

    return {
        "menu": manifest.frontend.get("menu", []),
        "panel": manifest.frontend.get("panel", {}),
    }
