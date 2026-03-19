from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

APP_IMPORT = os.environ.get("PIVOTDESK_APP", "app:app")
PORT = int(os.environ.get("PIVOTDESK_PORT", "8091"))
OPEN_BROWSER = os.environ.get("PIVOTDESK_OPEN_BROWSER", "1") not in {"0", "false", "False"}

BASE_DIR = Path(__file__).resolve().parent
IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else None
    except Exception:
        return None


def detect_license_type() -> str:
    appdata = os.getenv("APPDATA")
    candidates = []
    if appdata:
        candidates.append(Path(appdata) / "PivotDesk" / "license.json")
    candidates.append(BASE_DIR / "PivotDesk" / "license.json")
    candidates.extend([
        BASE_DIR / "licenses" / "dev-license.json",
        BASE_DIR / "licenses" / "demo-license.json",
    ])

    for path in candidates:
        data = _read_json(path)
        if not data:
            continue
        value = str(data.get("license_type") or data.get("edition") or "").strip().lower()
        if value:
            return value
    return "demo"


def license_allows_lan_access(license_type: str) -> bool:
    return str(license_type or "").strip().lower() in {"dev", "developer", "full"}


def resolve_host() -> str:
    configured = os.environ.get("PIVOTDESK_HOST", "127.0.0.1")
    configured = str(configured or "").strip() or "127.0.0.1"
    if configured in {"127.0.0.1", "localhost", "::1"} and license_allows_lan_access(detect_license_type()):
        return "0.0.0.0"
    return configured


HOST = resolve_host()
PUBLIC_HOST = "127.0.0.1" if HOST == "0.0.0.0" else HOST


def is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for_server(host: str, port: int, timeout: float = 20.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if is_port_open(host, port):
            return True
        time.sleep(0.25)
    return False


def open_browser_when_ready(host: str, port: int) -> None:
    if not OPEN_BROWSER:
        return

    def _worker() -> None:
        probe_host = "127.0.0.1" if host == "0.0.0.0" else host
        if wait_for_server(probe_host, port, timeout=20.0):
            webbrowser.open(f"http://{PUBLIC_HOST}:{port}/")

    threading.Thread(target=_worker, daemon=True).start()


def print_banner() -> None:
    system_name = platform.system()
    print(f"PivotDesk launcher")
    print(f"Sistema operativo: {system_name}")
    print(f"Cartella base: {BASE_DIR}")
    print(f"App import: {APP_IMPORT}")
    print(f"Server: http://{PUBLIC_HOST}:{PORT}/")


def ensure_dependencies() -> None:
    try:
        import uvicorn  # noqa: F401
    except Exception as exc:
        raise RuntimeError(
            "Dipendenza mancante: uvicorn. Installa i requisiti con:\n"
            "python -m pip install -r requirements.txt"
        ) from exc


def run_uvicorn() -> int:
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        APP_IMPORT,
        "--host",
        HOST,
        "--port",
        str(PORT),
    ]

    print("Avvio server...")
    print("Comando:", " ".join(cmd))
    open_browser_when_ready(HOST, PORT)

    proc = subprocess.Popen(cmd, cwd=str(BASE_DIR))
    try:
        return proc.wait()
    except KeyboardInterrupt:
        print("\nArresto PivotDesk...")
        proc.terminate()
        try:
            return proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            return proc.wait()


def main() -> int:
    print_banner()

    if is_port_open(HOST, PORT):
        print(f"Attenzione: la porta {PORT} risulta già in uso.")
        print(f"Prova ad aprire: http://{PUBLIC_HOST}:{PORT}/")
        if OPEN_BROWSER:
            webbrowser.open(f"http://{PUBLIC_HOST}:{PORT}/")
        return 0

    ensure_dependencies()
    return run_uvicorn()


if __name__ == "__main__":
    raise SystemExit(main())
