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


def load_config() -> dict:
    cfg_paths = [
        BASE_DIR / "config.json",
        BASE_DIR / "user_data" / "config.json",
    ]
    for cfg_file in cfg_paths:
        payload = _read_json(cfg_file)
        if isinstance(payload, dict):
            return payload
    return {}


def detect_license_type() -> str:
    appdata = os.getenv("APPDATA")
    candidates: list[Path] = []

    # Percorso configurato in data/license_settings.json (se presente)
    settings_candidates = [
        BASE_DIR / "data" / "license_settings.json",
        BASE_DIR / "user_data" / "license_settings.json",
    ]
    for settings_path in settings_candidates:
        settings_data = _read_json(settings_path) or {}
        configured_license_file = str(settings_data.get("license_file") or "").strip()
        if configured_license_file:
            candidates.append(Path(configured_license_file))

    if appdata:
        candidates.append(Path(appdata) / "PivotDesk" / "license.json")
    candidates.append(BASE_DIR / "PivotDesk" / "license.json")
    candidates.append(BASE_DIR / "data" / "license.json")
    candidates.append(BASE_DIR / "user_data" / "license.json")
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
    value = str(license_type or "").strip().lower()
    if value in {"", "demo", "trial", "free", "community"}:
        return False
    return True


def resolve_public_lan_host() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if ip:
                return ip
    except Exception:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return "127.0.0.1"


def resolve_host() -> str:
    cfg = load_config()
    license_type = detect_license_type()
    configured = os.environ.get("PIVOTDESK_HOST", cfg.get("host", "127.0.0.1"))
    configured = str(configured or "").strip() or "127.0.0.1"
    if not license_allows_lan_access(license_type):
        return "127.0.0.1"
    if configured in {"127.0.0.1", "localhost", "::1"}:
        return "0.0.0.0"
    return configured


def resolve_port() -> int:
    cfg = load_config()
    value = os.environ.get("PIVOTDESK_PORT", cfg.get("port", 8091))
    try:
        return int(value)
    except Exception:
        return 8091


HOST = resolve_host()
PORT = resolve_port()
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
    license_type = detect_license_type()
    print(f"PivotDesk launcher")
    print(f"Sistema operativo: {system_name}")
    print(f"Cartella base: {BASE_DIR}")
    print(f"App import: {APP_IMPORT}")
    print(f"Licenza rilevata: {license_type}")
    print(f"Server: http://{PUBLIC_HOST}:{PORT}/")
    if HOST == "0.0.0.0":
        lan_host = resolve_public_lan_host()
        print(f"LAN: http://{lan_host}:{PORT}/")
        print("Nota LAN: verifica che il firewall del sistema consenta connessioni in ingresso sulla porta configurata.")


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

    child_env = os.environ.copy()
    child_env["PIVOTDESK_RUNTIME_BIND_HOST"] = str(HOST)
    child_env["PIVOTDESK_RUNTIME_BIND_PORT"] = str(PORT)

    proc = subprocess.Popen(cmd, cwd=str(BASE_DIR), env=child_env)
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
