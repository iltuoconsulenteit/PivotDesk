from __future__ import annotations

import atexit
import json
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import pystray
from PIL import Image

def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def base_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_base_dir() -> Path:
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent


def resource_path(*parts: str) -> Path:
    return resource_base_dir().joinpath(*parts)


BASE_DIR = base_dir()


def appdata_dir() -> Path:
    roaming = os.getenv("APPDATA")
    if roaming:
        path = Path(roaming) / "PivotDesk"
    else:
        path = BASE_DIR / "user_data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def local_log_dir() -> Path:
    local = os.getenv("LOCALAPPDATA")
    if local:
        path = Path(local) / "PivotDesk" / "logs"
    else:
        path = BASE_DIR / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


DATA_DIR = appdata_dir()
LOG_DIR = local_log_dir()

TRAY_LOG = LOG_DIR / "tray.log"
SERVER_STDOUT = LOG_DIR / "server_stdout.log"
SERVER_STDERR = LOG_DIR / "server_stderr.log"
TRAY_PID_FILE = LOG_DIR / "tray.pid"
SERVER_PID_FILE = LOG_DIR / "server.pid"
CONFIG_PATH = DATA_DIR / "config.json"

_server_proc: subprocess.Popen | None = None
_server_host: str | None = None
_server_port: int | None = None


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def detect_license_type() -> str:
    candidates: list[Path] = []

    settings_candidates = [
        BASE_DIR / "data" / "license_settings.json",
        appdata_dir() / "license_settings.json",
    ]
    for settings_path in settings_candidates:
        settings_data = _read_json(settings_path) or {}
        configured_license_file = str(settings_data.get("license_file") or "").strip()
        if configured_license_file:
            candidates.append(Path(configured_license_file))

    candidates.extend([
        appdata_dir() / "license.json",
        BASE_DIR / "PivotDesk" / "license.json",
        BASE_DIR / "data" / "license.json",
        BASE_DIR / "user_data" / "license.json",
        BASE_DIR / "licenses" / "dev-license.json",
        BASE_DIR / "licenses" / "demo-license.json",
    ])

    for path in candidates:
        payload = _read_json(path)
        if not payload:
            continue
        value = str(payload.get("license_type") or payload.get("edition") or "").strip().lower()
        if value:
            return value
    return "demo"


def license_allows_lan_access(license_type: str) -> bool:
    value = str(license_type or "").strip().lower()
    return value not in {"", "demo", "trial", "free", "community"}


def resolve_bind_host(config_host: str, license_type: str) -> str:
    host = str(config_host or "").strip() or "127.0.0.1"
    if not license_allows_lan_access(license_type):
        return "127.0.0.1"
    if host in {"127.0.0.1", "localhost", "::1"}:
        return "0.0.0.0"
    return host


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


def log(msg: str) -> None:
    with TRAY_LOG.open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def write_pid_file(path: Path, pid: int) -> None:
    path.write_text(str(pid), encoding="utf-8")


def remove_pid_file(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass


def load_config() -> dict:
    cfg_paths = [
        BASE_DIR / "config.json",
        CONFIG_PATH,
    ]
    for cfg_file in cfg_paths:
        try:
            if cfg_file.exists():
                return json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception as e:
            log(f"Errore lettura config {cfg_file}: {e}")
    return {}


def get_runtime_host() -> str:
    env_host = str(os.getenv("PIVOTDESK_HOST", "")).strip()
    if env_host:
        return env_host

    cfg = load_config()
    config_host = str(cfg.get("host", "127.0.0.1")).strip() or "127.0.0.1"
    return resolve_bind_host(config_host, detect_license_type())


def get_runtime_port(default_port: int = 8091) -> int:
    env_port = str(os.getenv("PIVOTDESK_PORT", "")).strip()
    if env_port.isdigit():
        return int(env_port)

    cfg = load_config()
    try:
        return int(cfg.get("port", default_port))
    except Exception:
        return default_port


def _icon_image() -> Image.Image:
    icon_path = resource_path("static", "img", "pivotdesk-icon.png")
    if not icon_path.exists():
        icon_path = BASE_DIR / "static" / "img" / "pivotdesk-icon.png"
    return Image.open(icon_path)


def wait_tcp(host: str, port: int, timeout: int = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.5):
                return True
        except OSError:
            time.sleep(1)
    return False


def wait_http_health(host: str, port: int, timeout: int = 30) -> bool:
    import urllib.request

    deadline = time.time() + timeout
    url = f"http://{host}:{port}/health"

    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    body = resp.read().decode("utf-8", errors="ignore").lower()
                    if '"ok": true' in body or '"ok":true' in body or '"status": "ready"' in body:
                        return True
                    return True
        except Exception:
            time.sleep(1)

    return False


def build_server_command(host: str, port: int) -> list[str] | None:
    if is_frozen():
        exe_candidate = Path(sys.executable).resolve().parent / "PivotDesk.exe"
        if not exe_candidate.exists():
            log(f"ERRORE: eseguibile server non trovato in modalità frozen: {exe_candidate}")
            return None
        return [str(exe_candidate), "--host", host, "--port", str(port), "--no-browser"]
    return [sys.executable, str(BASE_DIR / "main.py"), "--host", host, "--port", str(port), "--no-browser"]


def start_server() -> None:
    global _server_proc, _server_host, _server_port

    host = get_runtime_host()
    port = get_runtime_port()

    if _server_proc and _server_proc.poll() is None:
        log("Server già in esecuzione.")
        return

    cmd = build_server_command(host, port)
    if not cmd:
        return

    log(f"Avvio server: {' '.join(cmd)}")
    log(f"cwd={BASE_DIR}")
    log(f"host={host} port={port}")
    if host == "0.0.0.0":
        lan_host = resolve_public_lan_host()
        log(f"URL locale: http://127.0.0.1:{port}/")
        log(f"URL LAN: http://{lan_host}:{port}/")

    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0

    stdout_f = SERVER_STDOUT.open("a", encoding="utf-8")
    stderr_f = SERVER_STDERR.open("a", encoding="utf-8")

    env = os.environ.copy()
    env["PIVOTDESK_PORT"] = str(port)
    env["PIVOTDESK_HOST"] = host

    _server_proc = subprocess.Popen(
        cmd,
        cwd=str(BASE_DIR),
        stdout=stdout_f,
        stderr=stderr_f,
        creationflags=creationflags,
        env=env,
    )

    write_pid_file(SERVER_PID_FILE, _server_proc.pid)
    _server_host = host
    _server_port = port

    if _server_proc.poll() is not None:
        log(f"Server terminato subito. Return code={_server_proc.returncode}")
        remove_pid_file(SERVER_PID_FILE)
        return

    if wait_tcp(host, port, timeout=20):
        log(f"Porta TCP raggiungibile su {host}:{port}")
    else:
        log(f"Porta TCP NON raggiungibile su {host}:{port} entro timeout")

    if wait_http_health(host, port, timeout=25):
        log(f"Health OK su http://{host}:{port}/health")
    else:
        log(f"Health NON raggiungibile su http://{host}:{port}/health entro timeout")


def stop_server() -> None:
    global _server_proc, _server_host, _server_port

    if _server_proc and _server_proc.poll() is None:
        log("Arresto server...")
        _server_proc.terminate()
        try:
            _server_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            log("Timeout arresto server, kill forzato.")
            _server_proc.kill()

    _server_proc = None
    _server_host = None
    _server_port = None
    remove_pid_file(SERVER_PID_FILE)


def restart_server(icon=None, item=None) -> None:
    log("Riavvio server...")
    stop_server()
    time.sleep(0.5)
    start_server()


def open_dashboard(icon=None, item=None) -> None:
    host = get_runtime_host()
    port = get_runtime_port()
    browser_host = "127.0.0.1" if host == "0.0.0.0" else host

    log("Richiesta apertura dashboard.")

    if wait_http_health(browser_host, port, timeout=20):
        webbrowser.open(f"http://{browser_host}:{port}/login")
        log(f"Dashboard aperta su http://{browser_host}:{port}/login")
    else:
        log(f"Dashboard non pronta entro timeout, apertura forzata su http://{browser_host}:{port}/login")
        webbrowser.open(f"http://{browser_host}:{port}/login")


def quit_app(icon: pystray.Icon, item=None) -> None:
    log("Chiusura applicazione.")
    stop_server()
    remove_pid_file(TRAY_PID_FILE)
    icon.stop()


def _health_watchdog(icon: pystray.Icon) -> None:
    global _server_proc, _server_host, _server_port

    while True:
        if not icon.visible:
            break

        if _server_proc and _server_proc.poll() is not None:
            log(f"Watchdog: server chiuso con code={_server_proc.returncode}, riavvio...")
            remove_pid_file(SERVER_PID_FILE)
            start_server()
        elif _server_proc and _server_proc.poll() is None:
            desired_host = get_runtime_host()
            desired_port = get_runtime_port()
            if desired_host != _server_host or desired_port != _server_port:
                log(
                    "Watchdog: rilevata variazione configurazione LAN/bind "
                    f"({_server_host}:{_server_port} -> {desired_host}:{desired_port}), riavvio..."
                )
                restart_server()

        time.sleep(2)


def cleanup() -> None:
    remove_pid_file(TRAY_PID_FILE)
    remove_pid_file(SERVER_PID_FILE)


def main() -> None:
    atexit.register(cleanup)
    write_pid_file(TRAY_PID_FILE, os.getpid())

    log("=== Avvio PivotDesk tray ===")
    log(f"Host runtime: {get_runtime_host()}")
    log(f"Porta runtime: {get_runtime_port()}")

    start_server()

    t_open = threading.Thread(target=open_dashboard, daemon=True)
    t_open.start()

    icon = pystray.Icon(
        "PivotDesk",
        _icon_image(),
        "PivotDesk",
        menu=pystray.Menu(
            pystray.MenuItem("Apri dashboard", open_dashboard),
            pystray.MenuItem("Riavvia server", restart_server),
            pystray.MenuItem("Esci", quit_app),
        ),
    )

    t = threading.Thread(target=_health_watchdog, args=(icon,), daemon=True)
    t.start()
    icon.run()


if __name__ == "__main__":
    main()
