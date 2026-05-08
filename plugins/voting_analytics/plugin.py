from __future__ import annotations

import io
from datetime import datetime
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel, Field, conint


NonNegativeInt = conint(strict=True, ge=0)


class VotingAnalyticsRequest(BaseModel):
    source_id: str
    name_column: str
    votes_column: str
    extra_dimensions: list[str] = Field(default_factory=list)
    threshold_main: NonNegativeInt = 0
    threshold_min: NonNegativeInt = 0
    thresholds_as_percent: bool = False
    top_n: int = Field(default=200, ge=1, le=5000)


class VotingAnalyticsExportRequest(VotingAnalyticsRequest):
    fmt: str = Field(default="html")
    include_app_logo: bool = True
    include_dev_logo: bool = True
    title: str = Field(default="Voting Analytics Report")
    view_mode: str = Field(default="ranking")


def _normalize_status(votes: float, threshold_main: float, threshold_min: float) -> str:
    if votes >= threshold_main:
        return "Eletto"
    if votes >= threshold_min:
        return "Riserva"
    return "Escluso"


def _build_voting_result(plugin_api: Any, payload: VotingAnalyticsRequest) -> dict[str, Any]:
    if not plugin_api.get_source or not plugin_api.load_dataframe_from_source:
        raise HTTPException(status_code=500, detail="Plugin API incompleta")

    source = plugin_api.get_source(payload.source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Sorgente non trovata")

    try:
        df = plugin_api.load_dataframe_from_source(source).copy()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Errore caricamento sorgente: {exc}") from exc
    if payload.name_column not in df.columns:
        raise HTTPException(status_code=400, detail=f"Colonna nome mancante: {payload.name_column}")
    if payload.votes_column not in df.columns:
        raise HTTPException(status_code=400, detail=f"Colonna voti mancante: {payload.votes_column}")

    extra_dims = [c for c in payload.extra_dimensions if c in df.columns and c not in {payload.name_column, payload.votes_column}]

    work = pd.DataFrame()
    work["name"] = df[payload.name_column].fillna("").astype(str).str.strip()
    work["votes"] = pd.to_numeric(df[payload.votes_column], errors="coerce").fillna(0.0)
    for c in extra_dims:
        work[c] = df[c].fillna("").astype(str).str.strip()

    work = work[work["name"] != ""].copy()
    if work.empty:
        return {
            "ok": True,
            "ranking": [],
            "multi_column": {"Eletti": [], "Riserva": [], "Esclusi": [], "rows": []},
            "pivot_status": [],
            "summary": {
                "total_rows": 0,
                "total_votes": 0,
                "threshold_main": payload.threshold_main,
                "threshold_min": payload.threshold_min,
                "thresholds_as_percent": payload.thresholds_as_percent,
                "source_id": payload.source_id,
                "name_column": payload.name_column,
                "votes_column": payload.votes_column,
                "extra_dimensions": extra_dims,
            },
            "chart": {"ranking": {"labels": [], "values": []}, "status_distribution": {"labels": ["Eletto", "Riserva", "Escluso"], "values": [0, 0, 0]}},
        }

    total_votes = float(work["votes"].sum())
    threshold_main = float(payload.threshold_main)
    threshold_min = float(payload.threshold_min)
    if payload.thresholds_as_percent:
        threshold_main = total_votes * (threshold_main / 100.0)
        threshold_min = total_votes * (threshold_min / 100.0)

    work["status"] = work["votes"].map(lambda x: _normalize_status(float(x), threshold_main, threshold_min))

    work = work.sort_values(["votes", "name"], ascending=[False, True], kind="stable").reset_index(drop=True)
    work["rank"] = work.index + 1

    ranking_cols = ["rank", "name", "votes", "status"] + extra_dims
    ranking = work[ranking_cols].head(payload.top_n).fillna("").to_dict(orient="records")

    elected = work[work["status"] == "Eletto"]["name"].tolist()
    reserve = work[work["status"] == "Riserva"]["name"].tolist()
    excluded = work[work["status"] == "Escluso"]["name"].tolist()
    max_len = max(len(elected), len(reserve), len(excluded), 0)
    multi_rows: list[dict[str, Any]] = []
    for i in range(max_len):
        multi_rows.append({
            "Eletti": elected[i] if i < len(elected) else "",
            "Riserva": reserve[i] if i < len(reserve) else "",
            "Esclusi": excluded[i] if i < len(excluded) else "",
        })

    group_dims = extra_dims if extra_dims else ["status"]
    pivot_status = (
        work.groupby(group_dims + ["status"], dropna=False)
        .size()
        .reset_index(name="count")
        .fillna("")
        .to_dict(orient="records")
    )

    status_counts = work["status"].value_counts()
    chart = {
        "ranking": {
            "labels": [str(x) for x in work["name"].head(payload.top_n).tolist()],
            "values": [float(x) for x in work["votes"].head(payload.top_n).tolist()],
        },
        "status_distribution": {
            "labels": ["Eletto", "Riserva", "Escluso"],
            "values": [
                int(status_counts.get("Eletto", 0)),
                int(status_counts.get("Riserva", 0)),
                int(status_counts.get("Escluso", 0)),
            ],
        },
    }

    return {
        "ok": True,
        "ranking": ranking,
        "multi_column": {
            "Eletti": elected,
            "Riserva": reserve,
            "Esclusi": excluded,
            "rows": multi_rows,
        },
        "pivot_status": pivot_status,
        "summary": {
            "total_rows": int(len(work.index)),
            "total_votes": total_votes,
            "threshold_main": threshold_main,
            "threshold_min": threshold_min,
            "thresholds_as_percent": bool(payload.thresholds_as_percent),
            "source_id": payload.source_id,
            "name_column": payload.name_column,
            "votes_column": payload.votes_column,
            "extra_dimensions": extra_dims,
        },
        "chart": chart,
    }


def _escape_html(value: Any) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _render_html_table(rows: list[dict[str, Any]], ordered_columns: list[str]) -> str:
    head = "".join(f"<th>{_escape_html(c)}</th>" for c in ordered_columns)
    body_chunks = []
    for row in rows:
        body_chunks.append("<tr>" + "".join(f"<td>{_escape_html(row.get(c, ''))}</td>" for c in ordered_columns) + "</tr>")
    if not body_chunks:
        body_chunks.append(f"<tr><td colspan='{max(1, len(ordered_columns))}'>Nessun dato</td></tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_chunks)}</tbody></table>"


def _build_voting_report_html(result: dict[str, Any], title: str, include_app_logo: bool, include_dev_logo: bool, include_customer_logo: bool, customer_logo_url: str, view_mode: str = "ranking", auto_print: bool = False) -> str:
    ranking_rows = result.get("ranking") if isinstance(result.get("ranking"), list) else []
    ranking_cols = ["rank", "name", "votes", "status"]
    if ranking_rows:
        for key in ranking_rows[0].keys():
            if key not in ranking_cols:
                ranking_cols.append(key)

    pivot_rows = result.get("pivot_status") if isinstance(result.get("pivot_status"), list) else []
    pivot_cols = list(pivot_rows[0].keys()) if pivot_rows else ["status", "count"]

    multi_rows = ((result.get("multi_column") or {}).get("rows") if isinstance(result.get("multi_column"), dict) else []) or []
    multi_cols = ["Eletti", "Riserva", "Esclusi"]

    chart = result.get("chart") if isinstance(result.get("chart"), dict) else {}
    ranking_chart = chart.get("ranking") if isinstance(chart.get("ranking"), dict) else {}
    chart_labels = ranking_chart.get("labels") if isinstance(ranking_chart.get("labels"), list) else []
    chart_values = ranking_chart.get("values") if isinstance(ranking_chart.get("values"), list) else []

    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    source_id = str(summary.get("source_id") or "")
    total_rows = int(summary.get("total_rows") or 0)
    total_votes = float(summary.get("total_votes") or 0)
    threshold_main = float(summary.get("threshold_main") or 0)
    threshold_min = float(summary.get("threshold_min") or 0)

    customer_logo_html = ""
    if include_customer_logo and customer_logo_url:
        customer_logo_html = f'<div class="head-logo"><img src="{_escape_html(customer_logo_url)}" alt="Logo cliente"></div>'

    footer_parts: list[str] = []
    if include_app_logo:
        footer_parts.append('<div class="footer-logo"><img src="/static/img/pivotdesk-icon.png" alt="PivotDesk"></div>')
    if include_dev_logo:
        footer_parts.append('<div class="footer-logo"><img src="/static/img/IltuoConsulenteIT.png" alt="IlTuoConsulenteIT"></div>')
    footer_html = f"<div class='footer'>{''.join(footer_parts)}</div>" if footer_parts else ""

    max_chart = max([float(x) for x in chart_values if isinstance(x, (int, float))] + [0.0])
    chart_rows = []
    for idx, label in enumerate(chart_labels[:20]):
        val = float(chart_values[idx]) if idx < len(chart_values) and isinstance(chart_values[idx], (int, float)) else 0.0
        width = (val / max_chart * 100.0) if max_chart > 0 else 0.0
        chart_rows.append(
            "<div class='bar-row'><div class='bar-label'>"
            + _escape_html(label)
            + "</div><div class='bar-track'><div class='bar-fill' style='width:"
            + _escape_html(f"{width:.2f}")
            + "%;'></div></div><div class='bar-value'>"
            + _escape_html(f"{val:.2f}")
            + "</div></div>"
        )
    chart_html = "".join(chart_rows) if chart_rows else "<div class='muted'>Nessun dato grafico disponibile.</div>"

    section_mode = str(view_mode or "ranking").strip().lower()
    if section_mode not in {"ranking", "columns", "pivot", "chart", "all"}:
        section_mode = "ranking"

    body_sections: list[str] = []
    if section_mode in {"ranking", "all"}:
        body_sections.append("<div class='section'><h2>Classifica</h2>" + _render_html_table(ranking_rows, ranking_cols) + "</div>")
    if section_mode in {"columns", "all"}:
        body_sections.append("<div class='section'><h2>Colonne (Eletti / Riserva / Esclusi)</h2>" + _render_html_table(multi_rows, multi_cols) + "</div>")
    if section_mode in {"pivot", "all"}:
        body_sections.append("<div class='section'><h2>Distribuzione (vista pivot)</h2>" + _render_html_table(pivot_rows, pivot_cols) + "</div>")
    if section_mode in {"chart", "all"}:
        body_sections.append("<div class='section'><h2>Grafico ranking (Top 20)</h2>" + chart_html + "</div>")

    auto_print_script = "<script>window.addEventListener('load',()=>window.print());</script>" if auto_print else ""

    return (
        "<!doctype html><html lang='it'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{_escape_html(title)}</title>"
        "<style>"
        "@page{size:A4;margin:10mm;}"
        "*{box-sizing:border-box;}"
        "body{font-family:Arial,sans-serif;color:#111827;font-size:10pt;margin:0;padding:0;background:#fff;}"
        ".wrap{padding:6mm;}"
        ".head{display:flex;justify-content:space-between;gap:10mm;border-bottom:1px solid #d0d5dd;padding-bottom:4mm;margin-bottom:4mm;}"
        ".head h1{font-size:16pt;margin:0 0 2mm 0;}"
        ".meta{font-size:9pt;color:#475467;line-height:1.4;}"
        ".head-logo img{max-height:16mm;max-width:44mm;object-fit:contain;}"
        ".section{margin-top:4mm;}"
        ".section h2{font-size:11pt;margin:0 0 2mm 0;}"
        "table{width:100%;border-collapse:collapse;table-layout:fixed;}"
        "th,td{border:1px solid #d0d5dd;padding:2.5mm;font-size:9pt;word-break:break-word;}"
        "th{background:#eef2f7;text-align:left;}"
        ".summary-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:2mm 6mm;font-size:9pt;}"
        ".footer{margin-top:6mm;padding-top:3mm;border-top:1px solid #d0d5dd;display:flex;justify-content:space-between;align-items:center;gap:8mm;}"
        ".footer-logo img{height:4.2mm;max-width:22mm;object-fit:contain;opacity:.78;}"
        ".muted{color:#667085;font-size:9pt;}"
        ".bar-row{display:grid;grid-template-columns:minmax(120px,1fr) 3fr minmax(68px,auto);gap:6px;align-items:center;margin:4px 0;}"
        ".bar-track{height:10px;background:#eef2f7;border-radius:999px;overflow:hidden;}"
        ".bar-fill{height:100%;background:#4f46e5;}"
        ".bar-label,.bar-value{font-size:8.8pt;}"
        "</style>"
        f"{auto_print_script}"
        "</head><body><div class='wrap'>"
        f"<div class='head'><div><h1>{_escape_html(title)}</h1>"
        f"<div class='meta'><div><strong>Sorgente:</strong> {_escape_html(source_id)}</div>"
        f"<div><strong>Data report:</strong> {_escape_html(datetime.now().strftime('%d/%m/%Y %H:%M'))}</div></div></div>{customer_logo_html}</div>"
        "<div class='section'><h2>Riepilogo soglie</h2>"
        "<div class='summary-grid'>"
        f"<div><strong>Record analizzati:</strong> {_escape_html(total_rows)}</div>"
        f"<div><strong>Totale voti:</strong> {_escape_html(f'{total_votes:.2f}')}</div>"
        f"<div><strong>Soglia eletti:</strong> {_escape_html(f'{threshold_main:.2f}')}</div>"
        f"<div><strong>Soglia riserva:</strong> {_escape_html(f'{threshold_min:.2f}')}</div>"
        "</div></div>"
        f"{''.join(body_sections)}"
        f"{footer_html}"
        "</div></body></html>"
    )


def register(app, plugin_api, manifest):
    router = APIRouter(prefix="/plugin/voting-analytics", tags=["plugins", "voting_analytics"])

    @router.post("/process")
    def process_voting(payload: VotingAnalyticsRequest):
        return _build_voting_result(plugin_api, payload)

    @router.post("/export")
    def export_voting(payload: VotingAnalyticsExportRequest):
        result = _build_voting_result(plugin_api, payload)
        summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
        source_id = str(summary.get("source_id") or payload.source_id or "voting")
        filename_base = "voting_report_" + source_id.replace(" ", "_")

        license_ctx = plugin_api.get_license_context(prefer_online=False) if plugin_api.get_license_context else {}
        license_status = str((license_ctx or {}).get("license_status") or "").strip().lower()
        license_features = (license_ctx or {}).get("license_features") if isinstance((license_ctx or {}).get("license_features"), dict) else {}
        can_hide_branding = bool(license_features.get("print")) and license_status not in {"", "demo", "free", "trial", "community"}

        include_app_logo = bool(payload.include_app_logo)
        include_dev_logo = bool(payload.include_dev_logo)
        if not can_hide_branding:
            include_app_logo = True
            include_dev_logo = True

        customer_logo_url = str((license_ctx or {}).get("customer_logo_url") or "").strip()
        include_customer_logo = bool(customer_logo_url) and license_status not in {"", "demo", "free", "trial", "community"}

        fmt = str(payload.fmt or "html").strip().lower()
        if fmt == "xlsx":
            ranking_df = pd.DataFrame(result.get("ranking") or [])
            multi_df = pd.DataFrame((result.get("multi_column") or {}).get("rows") or [])
            pivot_df = pd.DataFrame(result.get("pivot_status") or [])
            summary_df = pd.DataFrame([result.get("summary") or {}])
            chart_df = pd.DataFrame({
                "label": ((result.get("chart") or {}).get("ranking") or {}).get("labels") or [],
                "value": ((result.get("chart") or {}).get("ranking") or {}).get("values") or [],
            })
            view_mode = str(payload.view_mode or "ranking").strip().lower()
            if view_mode not in {"ranking", "columns", "pivot", "chart", "all"}:
                view_mode = "ranking"

            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                summary_df.to_excel(writer, sheet_name="Riepilogo", index=False)
                if view_mode in {"ranking", "all"}:
                    ranking_df.to_excel(writer, sheet_name="Classifica", index=False)
                if view_mode in {"columns", "all"}:
                    multi_df.to_excel(writer, sheet_name="Colonne", index=False)
                if view_mode in {"pivot", "all"}:
                    pivot_df.to_excel(writer, sheet_name="Pivot", index=False)
                if view_mode in {"chart", "all"}:
                    chart_df.to_excel(writer, sheet_name="Grafico", index=False)
            output.seek(0)
            headers = {"Content-Disposition": f'attachment; filename="{filename_base}.xlsx"'}
            return StreamingResponse(
                output,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers=headers,
            )

        if fmt in {"html", "pdf"}:
            html = _build_voting_report_html(
                result=result,
                title=payload.title or "Voting Analytics Report",
                include_app_logo=include_app_logo,
                include_dev_logo=include_dev_logo,
                include_customer_logo=include_customer_logo,
                customer_logo_url=customer_logo_url,
                view_mode=payload.view_mode,
                auto_print=fmt == "pdf",
            )
            if fmt == "html":
                headers = {"Content-Disposition": f'attachment; filename="{filename_base}.html"'}
                return HTMLResponse(content=html, headers=headers)
            return HTMLResponse(content=html)

        raise HTTPException(status_code=400, detail="Formato export non supportato. Usa: html, pdf, xlsx")

    app.include_router(router)

    return {
        "tool_tab": "plugins",
        "card_id": "voting_analytics",
    }
