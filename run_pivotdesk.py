from __future__ import annotations

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
HOST = os.environ.get("PIVOTDESK_HOST", "127.0.0.1")
PORT = int(os.environ.get("PIVOTDESK_PORT", "8091"))
OPEN_BROWSER = os.environ.get("PIVOTDESK_OPEN_BROWSER", "1") not in {"0", "false", "False"}

BASE_DIR = Path(__file__).resolve().parent
IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"


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
        if wait_for_server(host, port, timeout=20.0):
            webbrowser.open(f"http://{host}:{port}/")

    threading.Thread(target=_worker, daemon=True).start()


def print_banner() -> None:
    system_name = platform.system()
    print(f"PivotDesk launcher")
    print(f"Sistema operativo: {system_name}")
    print(f"Cartella base: {BASE_DIR}")
    print(f"App import: {APP_IMPORT}")
    print(f"Server: http://{HOST}:{PORT}/")


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
        print(f"Prova ad aprire: http://{HOST}:{PORT}/")
        if OPEN_BROWSER:
            webbrowser.open(f"http://{HOST}:{PORT}/")
        return 0

    ensure_dependencies()
    return run_uvicorn()


if __name__ == "__main__":
    raise SystemExit(main())
