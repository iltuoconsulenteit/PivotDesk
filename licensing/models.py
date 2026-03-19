from dataclasses import dataclass
from typing import Any


@dataclass
class LicenseCheckResult:
    valid: bool
    status: str
    message: str
    license_data: dict[str, Any] | None = None
