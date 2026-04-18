from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from fastapi import File, Form, UploadFile
from fastapi.responses import JSONResponse


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _safe_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return re.sub(r"\s+", " ", text).strip()


def _flatten_element(el: ET.Element, prefix: str = "") -> dict[str, str]:
    row: dict[str, str] = {}
    tag = _strip_ns(el.tag)
    node_prefix = f"{prefix}.{tag}" if prefix else tag

    text = _safe_cell(el.text)
    children = list(el)
    if text and not children:
        row[node_prefix] = text

    grouped: dict[str, list[ET.Element]] = {}
    for child in children:
        grouped.setdefault(_strip_ns(child.tag), []).append(child)

    for child_tag, nodes in grouped.items():
        if len(nodes) == 1:
            row.update(_flatten_element(nodes[0], node_prefix))
        else:
            for i, node in enumerate(nodes, start=1):
                indexed = f"{node_prefix}.{child_tag}[{i}]"
                row.update(_flatten_element(node, indexed))
    return row


def _extract_row_from_xml(content: bytes, filename: str) -> dict[str, str]:
    root = ET.fromstring(content)
    row = _flatten_element(root)
    row["_xml_filename"] = _safe_cell(filename)
    row["_xml_root"] = _strip_ns(root.tag)
    return row


def _next_numeric_source_id(items: list[dict[str, Any]]) -> str:
    used: set[int] = set()
    for item in items:
        raw = str(item.get("id", "")).strip()
        try:
            n = int(raw)
            if n > 0:
                used.add(n)
        except Exception:
            continue
    n = (max(used) + 1) if used else 1
    while n in used:
        n += 1
    return str(n)


def register(app, plugin_api, manifest):
    @app.post("/plugin/xml-structured-import/upload")
    async def xml_structured_import_upload(
        files: list[UploadFile] = File(...),
        source_title: str = Form("XML import"),
    ):
        if not files:
            return JSONResponse({"error": "Nessun file XML ricevuto."}, status_code=400)

        rows: list[dict[str, str]] = []
        bad_files: list[dict[str, str]] = []
        for f in files:
            name = str(f.filename or "file.xml")
            raw = await f.read()
            if not raw:
                continue
            try:
                row = _extract_row_from_xml(raw, name)
                rows.append(row)
            except Exception as exc:
                bad_files.append({"file": name, "error": str(exc)})

        if not rows:
            return JSONResponse(
                {"error": "Impossibile leggere file XML validi.", "bad_files": bad_files},
                status_code=400,
            )

        all_cols = sorted({k for r in rows for k in r.keys()})
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        csv_name = f"xml_structured_{stamp}.csv"

        runtime_paths = plugin_api.get_runtime_paths() if callable(getattr(plugin_api, "get_runtime_paths", None)) else {}
        data_dir = Path(str(runtime_paths.get("data_dir", ".")))
        import_dir = data_dir / "import_data"
        import_dir.mkdir(parents=True, exist_ok=True)
        out_csv = import_dir / csv_name

        with out_csv.open("w", encoding="utf-8-sig", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=all_cols, delimiter=";")
            writer.writeheader()
            for row in rows:
                writer.writerow({c: row.get(c, "") for c in all_cols})

        bundle = plugin_api.get_sources_bundle() if callable(getattr(plugin_api, "get_sources_bundle", None)) else {}
        items = bundle.get("items", []) if isinstance(bundle, dict) else []
        source_id = _next_numeric_source_id(items if isinstance(items, list) else [])

        return {
            "ok": True,
            "rows": len(rows),
            "columns": all_cols,
            "csv_path": str(out_csv),
            "suggested_source_id": source_id,
            "suggested_source_title": f"{source_title.strip() or 'XML import'} {stamp}",
            "bad_files": bad_files,
            "note": "File CSV generato in import_data. La sorgente viene auto-rilevata al prossimo refresh sorgenti.",
        }

    return {
        "tool_tab": "plugins",
        "card_id": "xml_structured_import",
    }
