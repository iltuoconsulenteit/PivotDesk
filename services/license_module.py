from __future__ import annotations

import importlib
import logging
from typing import Any, Callable, Protocol


logger = logging.getLogger("pivotdesk.license_module")


class LicenseRuntimeModule(Protocol):
    def get_context(self, *, prefer_online: bool = False) -> dict[str, Any]:
        ...

    def get_available_providers(self) -> list[str]:
        ...

    def get_providers_payload(self, *, settings: dict[str, Any]) -> dict[str, Any]:
        ...

    def activate(self, *, provider_name: str, email: str, license_key: str) -> tuple[dict[str, Any], int]:
        ...

    def validate(self, *, prefer_online: bool = True) -> tuple[dict[str, Any], int]:
        ...

    def deactivate(self) -> tuple[dict[str, Any], int]:
        ...


def load_license_runtime_module(
    module_path: str,
    *,
    default_module: LicenseRuntimeModule,
) -> LicenseRuntimeModule:
    wanted = str(module_path or "").strip()
    if not wanted:
        return default_module

    try:
        mod = importlib.import_module(wanted)
    except Exception as exc:
        logger.warning("License runtime module import failed (%s): %s", wanted, exc)
        return default_module

    factory: Callable[..., Any] | None = getattr(mod, "create_license_module", None)
    if not callable(factory):
        logger.warning(
            "License runtime module '%s' has no callable create_license_module(default_module=...).",
            wanted,
        )
        return default_module

    try:
        candidate = factory(default_module=default_module)
    except Exception as exc:
        logger.warning("License runtime module factory failed (%s): %s", wanted, exc)
        return default_module

    required = (
        "get_context",
        "get_available_providers",
        "get_providers_payload",
        "activate",
        "validate",
        "deactivate",
    )
    if not all(callable(getattr(candidate, name, None)) for name in required):
        logger.warning(
            "License runtime module '%s' does not implement required methods: %s",
            wanted,
            ", ".join(required),
        )
        return default_module

    logger.info("License runtime module loaded: %s", wanted)
    return candidate
