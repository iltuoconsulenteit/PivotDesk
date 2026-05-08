from __future__ import annotations

import base64
import csv
import json
import re
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.config_loader import DATA_DIR


class ApiJobUpsertRequest(BaseModel):
    job_id: str | None = None
    title: str = Field(..., min_length=2)
    url: str = Field(..., min_length=8)
    method: str = "GET"
    auth_type: str = "none"  # none|basic|bearer
    username: str | None = None
    password: str | None = None
    token: str | None = None
    headers_json: str | None = None
    body_json: str | None = None
    schedule_type: str = "none"  # none|minutely|hourly|daily|weekly|monthly
    every_minutes: int = Field(default=0, ge=0, le=10080)
    every_hours: int = Field(default=0, ge=0, le=720)
    run_at_time: str | None = None  # HH:MM
    week_day: int | None = None  # 0=Mon..6=Sun
    month_day: int | None = None  # 1..31
    enabled: bool = True


class ApiRunRequest(BaseModel):
    force: bool = True


def _plugin_license_allowed(plugin_api, plugin_id: str = "api_data_scheduler") -> bool:
    ctx = plugin_api.get_license_context(prefer_online=False) if getattr(plugin_api, "get_license_context", None) else {}
    features = ctx.get("license_features", {}) if isinstance(ctx, dict) and isinstance(ctx.get("license_features"), dict) else {}
    if features.get("*") is True:
        return True
    if bool(ctx.get("license_is_dev")):
        return True
    if bool(features.get("plugins")):
        return True
    pid = str(plugin_id or "").strip().lower()
    if not pid:
        return False
    candidates = [pid, f"plugin_{pid}", f"plugins.{pid}", f"plugins:{pid}"]
    return any(bool(features.get(k)) for k in candidates)


def _jobs_path() -> Path:
    app_data = DATA_DIR / "app_data"
    app_data.mkdir(parents=True, exist_ok=True)
    return app_data / "api_scheduler_jobs.json"


def _load_jobs() -> list[dict[str, Any]]:
    path = _jobs_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        jobs = raw.get("jobs", []) if isinstance(raw, dict) else []
        if isinstance(jobs, list):
            return [x for x in jobs if isinstance(x, dict)]
    except Exception:
        pass
    return []


def _save_jobs(items: list[dict[str, Any]]) -> None:
    _jobs_path().write_text(json.dumps({"jobs": items}, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_job_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(value or "").strip())
    return cleaned.strip("_").lower()


def _next_job_id(items: list[dict[str, Any]], wanted: str | None = None) -> str:
    requested = _normalize_job_id(str(wanted or ""))
    existing = {str(x.get("job_id", "")).strip() for x in items if isinstance(x, dict)}
    if requested and requested not in existing:
        return requested
    n = 1
    while True:
        candidate = f"api_job_{n}"
        if candidate not in existing:
            return candidate
        n += 1


def _parse_json_or_empty(raw: str | None, field_name: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} non è JSON valido") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail=f"{field_name} deve essere un oggetto JSON")
    return data


def _job_request_headers(job: dict[str, Any]) -> dict[str, str]:
    headers = {str(k): str(v) for k, v in (_parse_json_or_empty(job.get("headers_json"), "headers_json")).items()}
    auth_type = str(job.get("auth_type") or "none").strip().lower()
    if auth_type == "basic":
        user = str(job.get("username") or "")
        password = str(job.get("password") or "")
        token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    elif auth_type == "bearer":
        token = str(job.get("token") or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    return headers


def _run_job(job: dict[str, Any]) -> dict[str, Any]:
    url = str(job.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL API mancante")
    method = str(job.get("method") or "GET").strip().upper() or "GET"
    headers = _job_request_headers(job)
    body_obj = _parse_json_or_empty(job.get("body_json"), "body_json")
    data_bytes = None
    if method in {"POST", "PUT", "PATCH"} and body_obj:
        headers.setdefault("Content-Type", "application/json")
        data_bytes = json.dumps(body_obj, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url=url, method=method, headers=headers, data=data_bytes)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
            status = int(resp.getcode() or 200)
            content_type = str(resp.headers.get("Content-Type") or "")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Errore chiamata API: {exc}") from exc

    text = body.decode("utf-8", "ignore")
    parsed: Any
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = {"raw": text}

    out_dir = DATA_DIR / "generated_sources" / "api_scheduler"
    out_dir.mkdir(parents=True, exist_ok=True)
    job_id = _normalize_job_id(str(job.get("job_id") or "job")) or "job"
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    latest_path = out_dir / f"{job_id}.json"
    history_path = out_dir / f"{job_id}_{stamp}.json"
    payload = {
        "job_id": job_id,
        "fetched_at": datetime.utcnow().isoformat(),
        "status_code": status,
        "content_type": content_type,
        "data": parsed,
    }
    latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    history_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_rows: list[dict[str, Any]]
    if isinstance(parsed, list) and parsed and all(isinstance(x, dict) for x in parsed):
        csv_rows = [x for x in parsed if isinstance(x, dict)]
    elif isinstance(parsed, dict):
        items = parsed.get("items")
        if isinstance(items, list) and items and all(isinstance(x, dict) for x in items):
            csv_rows = [x for x in items if isinstance(x, dict)]
        else:
            csv_rows = [parsed]
    else:
        csv_rows = [{"value": json.dumps(parsed, ensure_ascii=False)}]

    fieldnames: list[str] = []
    for row in csv_rows:
        for key in row.keys():
            sk = str(key)
            if sk not in fieldnames:
                fieldnames.append(sk)
    if not fieldnames:
        fieldnames = ["value"]
        csv_rows = [{"value": ""}]

    import_dir = DATA_DIR / "import_data"
    import_dir.mkdir(parents=True, exist_ok=True)
    import_csv = import_dir / f"api_{job_id}.csv"
    with import_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in csv_rows:
            writer.writerow({c: row.get(c, "") for c in fieldnames})

    return {
        "ok": True,
        "job_id": job_id,
        "status_code": status,
        "content_type": content_type,
        "saved_latest": str(latest_path),
        "saved_history": str(history_path),
        "import_csv_path": str(import_csv),
        "preview_type": "list" if isinstance(parsed, list) else type(parsed).__name__,
    }


def _parse_hhmm(value: str | None) -> tuple[int, int] | None:
    raw = str(value or "").strip()
    m = re.match(r"^([0-1]?[0-9]|2[0-3]):([0-5][0-9])$", raw)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _is_job_due(job: dict[str, Any], now: datetime) -> bool:
    mode = str(job.get("schedule_type") or "none").strip().lower()
    if mode == "none":
        legacy_interval = int(job.get("interval_minutes") or 0)
        if legacy_interval > 0:
            mode = "minutely"
            job["every_minutes"] = legacy_interval
        else:
            return False

    last_raw = str(job.get("last_run_at") or "").strip()
    last_dt: datetime | None = None
    if last_raw:
        try:
            last_dt = datetime.fromisoformat(last_raw)
        except Exception:
            last_dt = None

    if mode == "minutely":
        every = int(job.get("every_minutes") or 0)
        if every <= 0:
            return False
        if not last_dt:
            return True
        return now >= (last_dt + timedelta(minutes=every))

    if mode == "hourly":
        every = int(job.get("every_hours") or 0)
        if every <= 0:
            return False
        if not last_dt:
            return True
        return now >= (last_dt + timedelta(hours=every))

    hhmm = _parse_hhmm(job.get("run_at_time"))
    if mode == "daily":
        if not hhmm:
            return False
        target = now.replace(hour=hhmm[0], minute=hhmm[1], second=0, microsecond=0)
        if now < target:
            return False
        if not last_dt:
            return True
        return last_dt.date() < now.date()

    if mode == "weekly":
        if not hhmm:
            return False
        weekday = int(job.get("week_day") if job.get("week_day") is not None else -1)
        if weekday < 0 or weekday > 6:
            return False
        if now.weekday() != weekday:
            return False
        target = now.replace(hour=hhmm[0], minute=hhmm[1], second=0, microsecond=0)
        if now < target:
            return False
        if not last_dt:
            return True
        return last_dt.date() < now.date()

    if mode == "monthly":
        if not hhmm:
            return False
        month_day = int(job.get("month_day") if job.get("month_day") is not None else 0)
        if month_day < 1 or month_day > 31:
            return False
        if now.day != month_day:
            return False
        target = now.replace(hour=hhmm[0], minute=hhmm[1], second=0, microsecond=0)
        if now < target:
            return False
        if not last_dt:
            return True
        return (last_dt.year, last_dt.month, last_dt.day) != (now.year, now.month, now.day)

    return False


def register(app, plugin_api, manifest):
    router = APIRouter(prefix="/plugin/api-scheduler", tags=["plugins", "api_scheduler"])

    def ensure_plugin_allowed() -> None:
        if not _plugin_license_allowed(plugin_api, "api_data_scheduler"):
            raise HTTPException(status_code=403, detail="Plugin API Data Scheduler non abilitato dalla licenza.")

    @router.get("/jobs/list")
    def list_jobs():
        ensure_plugin_allowed()
        items = _load_jobs()
        return {"ok": True, "jobs": items, "count": len(items)}

    @router.post("/jobs/save")
    def save_job(payload: ApiJobUpsertRequest):
        ensure_plugin_allowed()
        items = _load_jobs()
        wanted = _next_job_id(items, payload.job_id)
        job = {
            "job_id": wanted,
            "title": str(payload.title or wanted).strip(),
            "url": str(payload.url or "").strip(),
            "method": str(payload.method or "GET").strip().upper(),
            "auth_type": str(payload.auth_type or "none").strip().lower(),
            "username": str(payload.username or ""),
            "password": str(payload.password or ""),
            "token": str(payload.token or ""),
            "headers_json": str(payload.headers_json or "").strip(),
            "body_json": str(payload.body_json or "").strip(),
            "schedule_type": str(payload.schedule_type or "none").strip().lower(),
            "every_minutes": int(payload.every_minutes or 0),
            "every_hours": int(payload.every_hours or 0),
            "run_at_time": str(payload.run_at_time or "").strip(),
            "week_day": (int(payload.week_day) if payload.week_day is not None else None),
            "month_day": (int(payload.month_day) if payload.month_day is not None else None),
            "enabled": bool(payload.enabled),
            "updated_at": datetime.utcnow().isoformat(),
            "last_run_at": None,
            "last_status": None,
        }
        replaced = False
        requested = _normalize_job_id(str(payload.job_id or ""))
        for i, row in enumerate(items):
            rid = str(row.get("job_id") or "")
            if rid == requested or rid == wanted:
                old = row if isinstance(row, dict) else {}
                job["last_run_at"] = old.get("last_run_at")
                job["last_status"] = old.get("last_status")
                items[i] = job
                replaced = True
                break
        if not replaced:
            items.append(job)
        _save_jobs(items)
        return {"ok": True, "job": job}

    @router.delete("/jobs/{job_id}")
    def delete_job(job_id: str):
        ensure_plugin_allowed()
        items = _load_jobs()
        before = len(items)
        items = [x for x in items if str(x.get("job_id") or "") != str(job_id or "")]
        if len(items) == before:
            raise HTTPException(status_code=404, detail="Job non trovato")
        _save_jobs(items)
        return {"ok": True, "deleted": job_id}

    @router.post("/run/{job_id}")
    def run_job(job_id: str, payload: ApiRunRequest | None = None):
        ensure_plugin_allowed()
        _ = payload
        items = _load_jobs()
        found = next((x for x in items if str(x.get("job_id") or "") == str(job_id or "")), None)
        if not found:
            raise HTTPException(status_code=404, detail="Job non trovato")
        result = _run_job(found)
        found["last_run_at"] = datetime.utcnow().isoformat()
        found["last_status"] = int(result.get("status_code") or 0)
        _save_jobs(items)
        return result

    @router.post("/run-due")
    def run_due_jobs():
        ensure_plugin_allowed()
        items = _load_jobs()
        now = datetime.utcnow()
        ran: list[dict[str, Any]] = []
        skipped = 0
        for job in items:
            if not bool(job.get("enabled")):
                skipped += 1
                continue
            if not _is_job_due(job, now):
                skipped += 1
                continue
            try:
                result = _run_job(job)
                job["last_run_at"] = datetime.utcnow().isoformat()
                job["last_status"] = int(result.get("status_code") or 0)
                note = ""
                if str(job.get("schedule_type") or "").lower() == "minutely" and int(job.get("every_minutes") or 0) > 0 and int(job.get("every_minutes") or 0) < 15:
                    note = "Intervallo minuti molto basso: possibile sovraccarico server."
                ran.append({"job_id": job.get("job_id"), "ok": True, "status_code": job.get("last_status"), "warning": note})
            except HTTPException as exc:
                job["last_run_at"] = datetime.utcnow().isoformat()
                job["last_status"] = 0
                ran.append({"job_id": job.get("job_id"), "ok": False, "error": str(exc.detail)})
        _save_jobs(items)
        return {"ok": True, "ran": ran, "run_count": len(ran), "skipped": skipped}

    app.include_router(router)
    return {
        "menu": manifest.frontend.get("menu", []),
        "panel": manifest.frontend.get("panel", {}),
    }
