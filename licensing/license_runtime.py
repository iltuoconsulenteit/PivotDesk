from .activation_store import resolve_license_path
from .license_verify import verify_license_file

FEATURE_LABELS = {
    "subtotals": "subtotali",
    "preview": "anteprima",
    "print": "stampa",
}


def get_runtime_license_context() -> dict:
    result = verify_license_file(resolve_license_path())
    data = result.license_data or {}
    features = data.get("features", {}) if isinstance(data, dict) else {}

    disabled = []
    if result.valid and result.status == "demo":
        for key in ("subtotals", "preview", "print"):
            if not bool(features.get(key, False)):
                disabled.append(key)

    message = result.message
    if disabled and result.status == "demo":
        labels = ", ".join(FEATURE_LABELS.get(x, x) for x in disabled)
        message = f"{result.message}. Funzioni non disponibili: {labels}."

    return {
        "valid": result.valid,
        "status": result.status,
        "message": message,
        "is_demo": result.valid and result.status == "demo",
        "disabled_features": disabled,
        "license_data": data,
    }
