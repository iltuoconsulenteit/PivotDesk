import os
from pathlib import Path

PRODUCT_NAME = "PivotDesk"


def get_appdata_dir(product_name: str = PRODUCT_NAME) -> Path:
    appdata = os.getenv("APPDATA")
    if appdata:
        path = Path(appdata) / product_name
    else:
        path = Path.home() / f".{product_name.lower()}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_installed_license_path(product_name: str = PRODUCT_NAME) -> Path:
    return get_appdata_dir(product_name) / "license.json"


def get_demo_license_path() -> Path:
    return Path(__file__).resolve().parent.parent / "licenses" / "demo-license.json"


def resolve_license_path(product_name: str = PRODUCT_NAME) -> Path:
    installed = get_installed_license_path(product_name)
    return installed if installed.exists() else get_demo_license_path()
