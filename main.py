import json
import os
import signal
import socket
import sys
import threading
import time
import webbrowser
import argparse
from pathlib import Path

import uvicorn


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def base_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = base_dir()

# Fix fondamentale per Python embedded:
# assicura che la root del progetto sia importabile
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


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


def write_log(message: str) -> None:
    try:
        logfile = local_log_dir() / "launcher.log"
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with logfile.open("a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


def load_config() -> dict:
    cfg_paths = [
        BASE_DIR / "config.json",
        appdata_dir() / "config.json",
    ]

    for cfg_file in cfg_paths:
        if cfg_file.exists():
            try:
                with cfg_file.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                write_log(f"Errore lettura config {cfg_file}: {exc!r}")

    return {}


def read_json_file(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
            return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def detect_license_type() -> str:
    candidates = []

    settings_candidates = [
        BASE_DIR / "data" / "license_settings.json",
        appdata_dir() / "license_settings.json",
    ]
    for settings_path in settings_candidates:
        settings_data = read_json_file(settings_path) or {}
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
        data = read_json_file(path)
        if not data:
            continue
        license_type = str(data.get("license_type") or data.get("edition") or "").strip().lower()
        if license_type:
            return license_type
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


def resolve_bind_host(config_host: str, license_type: str) -> str:
    host = str(config_host or "").strip() or "127.0.0.1"
    if not license_allows_lan_access(license_type):
        return "127.0.0.1"
    if host in {"127.0.0.1", "localhost", "::1"}:
        return "0.0.0.0"
    return host


APP_HOST = "127.0.0.1"
APP_PORT = 8091
APP_PUBLIC_HOST = "127.0.0.1"
APP_URL = "http://127.0.0.1:8091"
APP_LOGIN_URL = "http://127.0.0.1:8091/login"
LICENSE_TYPE = "demo"


def port_is_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for_server(host: str, port: int, timeout: int = 30) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if port_is_open(host, port):
            return True
        time.sleep(0.5)
    return False


def wait_for_server_with_splash(host: str, port: int, timeout: int = 30) -> bool:
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception:
        return wait_for_server(host, port, timeout=timeout)

    root = tk.Tk()
    root.title("PivotDesk")
    root.geometry("520x230")
    root.resizable(False, False)
    root.configure(bg="white")
    root.attributes("-topmost", True)

    frame = tk.Frame(root, bg="white")
    frame.pack(fill="both", expand=True, padx=16, pady=14)

    logo_path = BASE_DIR / "static" / "img" / "pivotdesk-logo.png"
    logo_img = None
    if logo_path.exists():
        try:
            logo_img = tk.PhotoImage(file=str(logo_path))
            logo_label = tk.Label(frame, image=logo_img, bg="white")
            logo_label.pack(pady=(2, 8))
        except Exception:
            logo_img = None

    title = tk.Label(frame, text="PivotDesk in avvio...", font=("Segoe UI", 12, "bold"), bg="white", fg="#101828")
    title.pack(pady=(0, 6))
    status_var = tk.StringVar(value="Inizializzazione server in corso...")
    status = tk.Label(frame, textvariable=status_var, font=("Segoe UI", 10), bg="white", fg="#475467")
    status.pack(pady=(0, 10))

    progress = ttk.Progressbar(frame, orient="horizontal", mode="determinate", maximum=100, length=460)
    progress.pack(pady=(0, 8))
    hint = tk.Label(frame, text="Attendere prego, l'apertura iniziale può richiedere alcuni secondi.", font=("Segoe UI", 9), bg="white", fg="#667085")
    hint.pack()

    root.update_idletasks()
    root.update()

    start = time.time()
    ok = False
    while time.time() - start < timeout:
        if port_is_open(host, port):
            ok = True
            break
        elapsed = time.time() - start
        pct = min(98.0, (elapsed / max(1.0, timeout)) * 100.0)
        progress["value"] = pct
        status_var.set(f"Avvio servizio web... {int(elapsed)}s")
        try:
            root.update_idletasks()
            root.update()
        except Exception:
            # Se la finestra viene chiusa manualmente, continuiamo comunque l'attesa.
            pass
        time.sleep(0.2)

    progress["value"] = 100 if ok else progress["value"]
    status_var.set("Server pronto." if ok else "Timeout in attesa server.")
    try:
        root.update_idletasks()
        root.update()
        time.sleep(0.25)
    except Exception:
        pass
    try:
        root.destroy()
    except Exception:
        pass
    return ok


def run_server() -> None:
    write_log("Avvio server uvicorn")
    write_log(f"BASE_DIR={BASE_DIR}")
    write_log(f"sys.path={sys.path!r}")

    try:
        from app import app as fastapi_app

        os.environ["PIVOTDESK_RUNTIME_BIND_HOST"] = str(APP_HOST)
        os.environ["PIVOTDESK_RUNTIME_BIND_PORT"] = str(APP_PORT)

        uvicorn.run(
            fastapi_app,
            host=APP_HOST,
            port=APP_PORT,
            reload=False,
            workers=1,
            log_level="info",
        )
    except Exception as exc:
        write_log(f"Errore server: {exc!r}")
        raise


def main() -> None:
    global APP_HOST, APP_PORT, APP_PUBLIC_HOST, APP_URL, APP_LOGIN_URL, LICENSE_TYPE

    parser = argparse.ArgumentParser(description="PivotDesk server launcher")
    parser.add_argument("--host", dest="host", default=None, help="Override bind host")
    parser.add_argument("--port", dest="port", type=int, default=None, help="Override bind port")
    parser.add_argument("--no-browser", dest="no_browser", action="store_true", help="Do not open browser automatically")
    args = parser.parse_args()

    cfg = load_config()
    LICENSE_TYPE = detect_license_type()
    config_host = cfg.get("host", "127.0.0.1")
    if args.host:
        config_host = args.host
    APP_HOST = resolve_bind_host(config_host, LICENSE_TYPE)
    if args.port is not None:
        APP_PORT = int(args.port)
    else:
        APP_PORT = int(cfg.get("port", 8091))
    APP_PUBLIC_HOST = "127.0.0.1" if APP_HOST == "0.0.0.0" else APP_HOST
    APP_URL = f"http://{APP_PUBLIC_HOST}:{APP_PORT}"
    APP_LOGIN_URL = f"{APP_URL}/login"

    write_log("=== PivotDesk START ===")
    write_log(f"Frozen: {is_frozen()}")
    write_log(f"Base dir: {BASE_DIR}")
    write_log(f"AppData dir: {appdata_dir()}")
    write_log(f"CLI args: host={args.host!r} port={args.port!r} no_browser={args.no_browser!r}")
    write_log(f"Licenza rilevata: {LICENSE_TYPE}")
    write_log(f"Host bind: {APP_HOST}")
    write_log(f"Host browser: {APP_PUBLIC_HOST}")
    write_log(f"Porta: {APP_PORT}")
    if APP_HOST == "0.0.0.0":
        write_log(f"LAN URL suggerito: http://{resolve_public_lan_host()}:{APP_PORT}")
        write_log("Nota: verificare regole firewall in ingresso sulla porta dell'app.")

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    if wait_for_server_with_splash(APP_PUBLIC_HOST, APP_PORT, timeout=35):
        write_log(f"Server raggiungibile su {APP_URL}")
        if args.no_browser:
            write_log("Apertura browser disabilitata da --no-browser")
        else:
            try:
                webbrowser.open(APP_LOGIN_URL)
                write_log(f"Browser aperto su {APP_LOGIN_URL}")
            except Exception as exc:
                write_log(f"Errore apertura browser: {exc!r}")
    else:
        write_log("Server non raggiungibile entro il timeout")
        return

    stop_event = threading.Event()

    def handle_signal(sig, frame):
        write_log(f"Segnale ricevuto: {sig}")
        stop_event.set()

    try:
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)
    except Exception:
        pass

    write_log("Launcher in attesa")

    try:
        while not stop_event.is_set():
            if not server_thread.is_alive():
                write_log("Thread server terminato")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        write_log("KeyboardInterrupt ricevuto")
    finally:
        write_log("=== PivotDesk STOP ===")


if __name__ == "__main__":
    main()
