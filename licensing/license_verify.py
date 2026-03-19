import json
from pathlib import Path

from .models import LicenseCheckResult

EXPECTED_VENDOR = "IlTuoConsulenteIT"
EXPECTED_PRODUCT = "PivotDesk"


def verify_license_file(path: str | Path) -> LicenseCheckResult:
    p = Path(path)
    if not p.exists():
        return LicenseCheckResult(False, "missing", "File licenza non trovato")

    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        return LicenseCheckResult(False, "invalid_json", f"JSON non valido: {exc}")

    if data.get("vendor") != EXPECTED_VENDOR:
        return LicenseCheckResult(False, "wrong_vendor", "Licenza emessa per altro vendor")

    if data.get("product") != EXPECTED_PRODUCT:
        return LicenseCheckResult(False, "wrong_product", "Licenza non valida per questo prodotto")

    license_type = str(data.get("license_type", "")).strip().lower()
    if license_type == "demo":
        return LicenseCheckResult(True, "demo", "Versione demo attiva", data)

    signature = data.get("signature")
    if not signature:
        return LicenseCheckResult(False, "missing_signature", "Firma mancante")

    return LicenseCheckResult(True, "full", "Licenza valida", data)
