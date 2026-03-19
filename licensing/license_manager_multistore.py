
from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import socket
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Protocol, Tuple

import requests


UTC = timezone.utc


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except Exception:
        return None


def iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json(data: Dict[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def machine_fingerprint(app_name: str = "PivotDesk") -> str:
    parts = [
        app_name,
        platform.node() or "",
        platform.system() or "",
        platform.machine() or "",
        hex(uuid.getnode()),
        socket.gethostname(),
    ]
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:32]


@dataclass
class LicenseRecord:
    provider: str
    status: str
    edition: str
    license_key: str
    customer_email: Optional[str] = None
    customer_name: Optional[str] = None
    product_id: Optional[str] = None
    variant_id: Optional[str] = None
    instance_id: Optional[str] = None
    machine_id: Optional[str] = None
    expires_at: Optional[str] = None
    maintenance_until: Optional[str] = None
    activated_at: Optional[str] = None
    last_validated_at: Optional[str] = None
    valid_until_offline: Optional[str] = None
    features: Dict[str, bool] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def expires_dt(self) -> Optional[datetime]:
        return parse_dt(self.expires_at)

    @property
    def maintenance_dt(self) -> Optional[datetime]:
        return parse_dt(self.maintenance_until)

    @property
    def valid_until_offline_dt(self) -> Optional[datetime]:
        return parse_dt(self.valid_until_offline)

    def is_active_now(self, now: Optional[datetime] = None) -> bool:
        now = now or utcnow()
        if self.status not in {"active", "inactive"}:
            return False
        if self.expires_dt and now > self.expires_dt:
            return False
        return True

    def has_feature(self, name: str) -> bool:
        return bool(self.features.get(name))


@dataclass
class ActivationResult:
    ok: bool
    message: str
    record: Optional[LicenseRecord] = None
    error_code: Optional[str] = None


class LicenseProvider(Protocol):
    name: str

    def activate(self, email: str, license_key: str, machine_id: str) -> ActivationResult:
        ...

    def validate(self, record: LicenseRecord) -> ActivationResult:
        ...

    def deactivate(self, record: LicenseRecord) -> ActivationResult:
        ...


@dataclass
class GumroadConfig:
    product_id: str
    verify_url: str = "https://api.gumroad.com/v2/licenses/verify"
    increment_uses_count: bool = False
    offline_days: int = 14
    timeout: int = 20
    extra_features: Dict[str, bool] = field(default_factory=dict)


class GumroadProvider:
    name = "gumroad"

    def __init__(self, config: GumroadConfig):
        self.config = config

    def activate(self, email: str, license_key: str, machine_id: str) -> ActivationResult:
        payload = {
            "product_id": self.config.product_id,
            "license_key": license_key,
            "increment_uses_count": "true" if self.config.increment_uses_count else "false",
        }
        try:
            response = requests.post(self.config.verify_url, data=payload, timeout=self.config.timeout)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            return ActivationResult(False, f"Gumroad non raggiungibile: {exc}", error_code="NETWORK_ERROR")

        if not data.get("success"):
            return ActivationResult(False, "Licenza Gumroad non valida.", error_code="INVALID_LICENSE")

        purchase = data.get("purchase", {})
        if email and purchase.get("email") and purchase.get("email").strip().lower() != email.strip().lower():
            return ActivationResult(False, "Email non corrispondente alla licenza Gumroad.", error_code="EMAIL_MISMATCH")

        features = {
            "lan": False,
            "plugins": True,
            "charts": True,
            "advanced_import": True,
            **self.config.extra_features,
        }

        now = utcnow()
        # Gumroad verify response does not expose a first-class activation instance.
        record = LicenseRecord(
            provider=self.name,
            status="active",
            edition="full",
            license_key=license_key,
            customer_email=purchase.get("email") or email,
            customer_name=purchase.get("full_name"),
            product_id=str(purchase.get("product_id") or self.config.product_id),
            machine_id=machine_id,
            activated_at=iso(now),
            last_validated_at=iso(now),
            valid_until_offline=iso(now + timedelta(days=self.config.offline_days)),
            features=features,
            raw=data,
        )
        return ActivationResult(True, "Licenza Gumroad attivata.", record=record)

    def validate(self, record: LicenseRecord) -> ActivationResult:
        return self.activate(record.customer_email or "", record.license_key, record.machine_id or machine_fingerprint())

    def deactivate(self, record: LicenseRecord) -> ActivationResult:
        # Gumroad verification API is stateless from the client perspective.
        record.status = "inactive"
        return ActivationResult(True, "Licenza Gumroad disattivata localmente.", record=record)


@dataclass
class LemonSqueezyConfig:
    store_id: Optional[str] = None
    product_id: Optional[str] = None
    variant_id: Optional[str] = None
    api_base: str = "https://api.lemonsqueezy.com/v1"
    offline_days: int = 14
    timeout: int = 20
    extra_features: Dict[str, bool] = field(default_factory=dict)


class LemonSqueezyProvider:
    name = "lemonsqueezy"

    def __init__(self, config: LemonSqueezyConfig):
        self.config = config

    def _post_form(self, endpoint: str, form: Dict[str, str]) -> Dict[str, Any]:
        url = f"{self.config.api_base}{endpoint}"
        response = requests.post(
            url,
            headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
            data=form,
            timeout=self.config.timeout,
        )
        response.raise_for_status()
        return response.json()

    def activate(self, email: str, license_key: str, machine_id: str) -> ActivationResult:
        try:
            data = self._post_form(
                "/licenses/activate",
                {"license_key": license_key, "instance_name": machine_id},
            )
        except Exception as exc:
            return ActivationResult(False, f"Lemon Squeezy non raggiungibile: {exc}", error_code="NETWORK_ERROR")

        if not data.get("activated"):
            return ActivationResult(False, data.get("error") or "Licenza Lemon Squeezy non attivata.", error_code="INVALID_LICENSE")

        meta = data.get("meta", {})
        lk = data.get("license_key", {})
        instance = data.get("instance", {})

        if email and meta.get("customer_email") and meta.get("customer_email").strip().lower() != email.strip().lower():
            return ActivationResult(False, "Email non corrispondente alla licenza Lemon Squeezy.", error_code="EMAIL_MISMATCH")

        if self.config.product_id and str(meta.get("product_id")) != str(self.config.product_id):
            return ActivationResult(False, "La licenza appartiene a un prodotto Lemon Squeezy diverso.", error_code="PRODUCT_MISMATCH")

        if self.config.variant_id and str(meta.get("variant_id")) != str(self.config.variant_id):
            return ActivationResult(False, "La licenza appartiene a una variante Lemon Squeezy diversa.", error_code="VARIANT_MISMATCH")

        features = {
            "lan": False,
            "plugins": True,
            "charts": True,
            "advanced_import": True,
            **self.config.extra_features,
        }

        now = utcnow()
        record = LicenseRecord(
            provider=self.name,
            status=str(lk.get("status") or "active"),
            edition="full",
            license_key=license_key,
            customer_email=meta.get("customer_email") or email,
            customer_name=meta.get("customer_name"),
            product_id=str(meta.get("product_id")) if meta.get("product_id") is not None else None,
            variant_id=str(meta.get("variant_id")) if meta.get("variant_id") is not None else None,
            instance_id=instance.get("id") or instance.get("identifier"),
            machine_id=machine_id,
            expires_at=lk.get("expires_at"),
            activated_at=iso(now),
            last_validated_at=iso(now),
            valid_until_offline=iso(now + timedelta(days=self.config.offline_days)),
            features=features,
            raw=data,
        )
        return ActivationResult(True, "Licenza Lemon Squeezy attivata.", record=record)

    def validate(self, record: LicenseRecord) -> ActivationResult:
        form = {"license_key": record.license_key}
        if record.instance_id:
            form["instance_id"] = record.instance_id
        try:
            data = self._post_form("/licenses/validate", form)
        except Exception as exc:
            return ActivationResult(False, f"Lemon Squeezy non raggiungibile: {exc}", error_code="NETWORK_ERROR")

        if not data.get("valid"):
            return ActivationResult(False, data.get("error") or "Licenza Lemon Squeezy non valida.", error_code="INVALID_LICENSE")

        meta = data.get("meta", {})
        lk = data.get("license_key", {})
        now = utcnow()

        record.status = str(lk.get("status") or record.status)
        record.customer_email = meta.get("customer_email") or record.customer_email
        record.customer_name = meta.get("customer_name") or record.customer_name
        record.expires_at = lk.get("expires_at") or record.expires_at
        record.last_validated_at = iso(now)
        record.valid_until_offline = iso(now + timedelta(days=self.config.offline_days))
        record.raw = data
        return ActivationResult(True, "Licenza Lemon Squeezy valida.", record=record)

    def deactivate(self, record: LicenseRecord) -> ActivationResult:
        if not record.instance_id:
            record.status = "inactive"
            return ActivationResult(True, "Istanza Lemon Squeezy non presente: disattivazione solo locale.", record=record)

        try:
            data = self._post_form("/licenses/deactivate", {"license_key": record.license_key, "instance_id": record.instance_id})
        except Exception as exc:
            return ActivationResult(False, f"Lemon Squeezy non raggiungibile: {exc}", error_code="NETWORK_ERROR")

        if not data.get("deactivated"):
            return ActivationResult(False, data.get("error") or "Disattivazione Lemon Squeezy fallita.", error_code="DEACTIVATE_FAILED")

        record.status = "inactive"
        record.raw = data
        return ActivationResult(True, "Licenza Lemon Squeezy disattivata.", record=record)


@dataclass
class CustomConfig:
    activate_url: str
    validate_url: str
    deactivate_url: Optional[str] = None
    api_key: Optional[str] = None
    timeout: int = 20


class CustomProvider:
    name = "custom"

    def __init__(self, config: CustomConfig):
        self.config = config

    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _to_record(self, data: Dict[str, Any]) -> LicenseRecord:
        lic = data["license"]
        return LicenseRecord(
            provider=self.name,
            status=lic.get("status", "active"),
            edition=lic.get("edition", "full"),
            license_key=lic["license_key"],
            customer_email=lic.get("customer_email"),
            customer_name=lic.get("customer_name"),
            product_id=lic.get("product_id"),
            variant_id=lic.get("variant_id"),
            instance_id=lic.get("instance_id"),
            machine_id=lic.get("machine_id"),
            expires_at=lic.get("expires_at"),
            maintenance_until=lic.get("maintenance_until"),
            activated_at=lic.get("activated_at"),
            last_validated_at=lic.get("last_validated_at"),
            valid_until_offline=lic.get("valid_until_offline"),
            features=lic.get("features", {}),
            raw=data,
        )

    def activate(self, email: str, license_key: str, machine_id: str) -> ActivationResult:
        payload = {"email": email, "license_key": license_key, "machine_id": machine_id}
        try:
            r = requests.post(self.config.activate_url, headers=self._headers(), data=json.dumps(payload), timeout=self.config.timeout)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            return ActivationResult(False, f"Server custom non raggiungibile: {exc}", error_code="NETWORK_ERROR")

        if not data.get("ok"):
            return ActivationResult(False, data.get("message") or "Attivazione custom fallita.", error_code=data.get("error_code"))

        return ActivationResult(True, data.get("message") or "Licenza custom attivata.", record=self._to_record(data))

    def validate(self, record: LicenseRecord) -> ActivationResult:
        payload = {
            "license_key": record.license_key,
            "machine_id": record.machine_id,
            "instance_id": record.instance_id,
        }
        try:
            r = requests.post(self.config.validate_url, headers=self._headers(), data=json.dumps(payload), timeout=self.config.timeout)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            return ActivationResult(False, f"Server custom non raggiungibile: {exc}", error_code="NETWORK_ERROR")

        if not data.get("ok"):
            return ActivationResult(False, data.get("message") or "Validazione custom fallita.", error_code=data.get("error_code"))

        return ActivationResult(True, data.get("message") or "Licenza custom valida.", record=self._to_record(data))

    def deactivate(self, record: LicenseRecord) -> ActivationResult:
        if not self.config.deactivate_url:
            record.status = "inactive"
            return ActivationResult(True, "Disattivazione solo locale.", record=record)

        payload = {
            "license_key": record.license_key,
            "machine_id": record.machine_id,
            "instance_id": record.instance_id,
        }
        try:
            r = requests.post(self.config.deactivate_url, headers=self._headers(), data=json.dumps(payload), timeout=self.config.timeout)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            return ActivationResult(False, f"Server custom non raggiungibile: {exc}", error_code="NETWORK_ERROR")

        if not data.get("ok"):
            return ActivationResult(False, data.get("message") or "Disattivazione custom fallita.", error_code=data.get("error_code"))

        record.status = "inactive"
        record.raw = data
        return ActivationResult(True, data.get("message") or "Licenza custom disattivata.", record=record)


@dataclass
class DeveloperConfig:
    allowed_keys: Tuple[str, ...] = ("PIVOTDESK-DEV",)
    customer_name: str = "Developer"
    customer_email: str = "developer@local"
    offline_days: int = 3650


class DeveloperProvider:
    name = "developer"

    def __init__(self, config: DeveloperConfig):
        self.config = config

    def activate(self, email: str, license_key: str, machine_id: str) -> ActivationResult:
        if license_key not in self.config.allowed_keys:
            return ActivationResult(False, "Developer key non valida.", error_code="INVALID_LICENSE")
        now = utcnow()
        record = LicenseRecord(
            provider=self.name,
            status="active",
            edition="developer",
            license_key=license_key,
            customer_email=email or self.config.customer_email,
            customer_name=self.config.customer_name,
            machine_id=machine_id,
            activated_at=iso(now),
            last_validated_at=iso(now),
            valid_until_offline=iso(now + timedelta(days=self.config.offline_days)),
            features={
                "lan": True,
                "plugins": True,
                "charts": True,
                "advanced_import": True,
                "api": True,
                "branding": True,
                "multiuser": True,
            },
            raw={"source": "developer"},
        )
        return ActivationResult(True, "Licenza developer attivata.", record=record)

    def validate(self, record: LicenseRecord) -> ActivationResult:
        if record.license_key not in self.config.allowed_keys:
            return ActivationResult(False, "Developer key non più valida.", error_code="INVALID_LICENSE")
        now = utcnow()
        record.last_validated_at = iso(now)
        record.valid_until_offline = iso(now + timedelta(days=self.config.offline_days))
        return ActivationResult(True, "Licenza developer valida.", record=record)

    def deactivate(self, record: LicenseRecord) -> ActivationResult:
        record.status = "inactive"
        return ActivationResult(True, "Licenza developer disattivata.", record=record)


@dataclass
class LicenseManagerConfig:
    license_file: str = "data/license.json"
    offline_grace_days: int = 14
    default_provider: str = "developer"


class LicenseManager:
    def __init__(self, providers: Dict[str, LicenseProvider], config: Optional[LicenseManagerConfig] = None):
        self.providers = providers
        self.config = config or LicenseManagerConfig()
        self.license_path = Path(self.config.license_file)
        self.license_path.parent.mkdir(parents=True, exist_ok=True)

    def get_machine_id(self) -> str:
        return machine_fingerprint("PivotDesk")

    def save(self, record: LicenseRecord) -> None:
        self.license_path.write_text(json.dumps(record.__dict__, indent=2, ensure_ascii=False), encoding="utf-8")

    def load(self) -> Optional[LicenseRecord]:
        if not self.license_path.exists():
            return None
        data = json.loads(self.license_path.read_text(encoding="utf-8"))
        return LicenseRecord(**data)

    def activate(self, provider_name: str, email: str, license_key: str) -> ActivationResult:
        provider = self.providers[provider_name]
        result = provider.activate(email=email, license_key=license_key, machine_id=self.get_machine_id())
        if result.ok and result.record:
            self.save(result.record)
        return result

    def validate_current(self, prefer_online: bool = True) -> ActivationResult:
        record = self.load()
        if not record:
            return ActivationResult(False, "Nessuna licenza locale presente.", error_code="NO_LICENSE")

        now = utcnow()
        if record.expires_dt and now > record.expires_dt:
            return ActivationResult(False, "Licenza scaduta.", record=record, error_code="EXPIRED")

        provider = self.providers.get(record.provider)
        if provider and prefer_online:
            result = provider.validate(record)
            if result.ok and result.record:
                self.save(result.record)
                return result

        if record.valid_until_offline_dt and now <= record.valid_until_offline_dt:
            return ActivationResult(True, "Licenza valida in cache offline.", record=record)

        return ActivationResult(False, "Licenza non validabile online e grace period offline esaurito.", record=record, error_code="OFFLINE_EXPIRED")

    def deactivate_current(self) -> ActivationResult:
        record = self.load()
        if not record:
            return ActivationResult(False, "Nessuna licenza locale presente.", error_code="NO_LICENSE")
        provider = self.providers.get(record.provider)
        if not provider:
            return ActivationResult(False, "Provider licenza non disponibile.", error_code="NO_PROVIDER")
        result = provider.deactivate(record)
        if result.ok and result.record:
            try:
                self.license_path.unlink(missing_ok=True)
            except Exception:
                pass
        return result

    def current_mode(self) -> str:
        result = self.validate_current(prefer_online=False)
        if result.ok and result.record:
            return result.record.edition
        return "demo"

    def has_feature(self, feature_name: str) -> bool:
        result = self.validate_current(prefer_online=False)
        return bool(result.ok and result.record and result.record.has_feature(feature_name))


def build_default_manager() -> LicenseManager:
    providers: Dict[str, LicenseProvider] = {
        "developer": DeveloperProvider(DeveloperConfig()),
        # Configure these from your app settings / env before use:
        # "gumroad": GumroadProvider(GumroadConfig(product_id="YOUR_GUMROAD_PRODUCT_ID")),
        # "lemonsqueezy": LemonSqueezyProvider(LemonSqueezyConfig(product_id="12345", variant_id="67890")),
        # "custom": CustomProvider(CustomConfig(
        #     activate_url="https://yourdomain.tld/api/license/activate",
        #     validate_url="https://yourdomain.tld/api/license/validate",
        #     deactivate_url="https://yourdomain.tld/api/license/deactivate",
        #     api_key="YOUR_PRIVATE_APP_KEY",
        # )),
    }
    return LicenseManager(providers=providers)


if __name__ == "__main__":
    manager = build_default_manager()
    print("Machine ID:", manager.get_machine_id())
