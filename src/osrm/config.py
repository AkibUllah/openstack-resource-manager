"""Configuration: defaults < ~/.osrm.toml < environment variables < CLI flags."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on 3.10 only
    import tomli as tomllib

DEFAULT_CONFIG_PATH = Path.home() / ".osrm.toml"


@dataclass(frozen=True)
class AuditThresholds:
    idle_days: int = 14  # SHUTOFF for this long -> idle
    idle_cpu_percent: float = 5.0  # ACTIVE below this average CPU -> idle
    oversized_cpu_percent: float = 10.0  # ACTIVE below this on a big flavor -> oversized
    oversized_min_vcpus: int = 4
    orphan_volume_days: int = 7  # AVAILABLE and unattached for this long -> orphaned
    unused_ip_days: int = 7


@dataclass(frozen=True)
class Config:
    backend: str = "fake"  # fake | openstack
    cloud: str | None = None  # clouds.yaml entry
    region: str | None = None
    pricing: Path | None = None  # custom pricing YAML
    audit: AuditThresholds = field(default_factory=AuditThresholds)
    source: str = "defaults"


def _from_toml(path: Path) -> Config:
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    audit = AuditThresholds(
        **{
            k: v
            for k, v in (data.get("audit") or {}).items()
            if k in AuditThresholds.__dataclass_fields__
        }
    )
    return Config(
        backend=str(data.get("backend", "fake")),
        cloud=data.get("cloud"),
        region=data.get("region"),
        pricing=Path(data["pricing"]).expanduser() if data.get("pricing") else None,
        audit=audit,
        source=str(path),
    )


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else None


def load_config(path: Path | None = None, env: dict[str, str] | None = None) -> Config:
    """Merge the TOML file (if present) with OSRM_* / OS_CLOUD environment variables.

    File lookup: explicit ``path`` (CLI ``--config``) > ``OSRM_CONFIG`` > ``~/.osrm.toml``.
    """
    environ = os.environ if env is None else env
    config_path = Path(path or environ.get("OSRM_CONFIG") or DEFAULT_CONFIG_PATH).expanduser()
    config = _from_toml(config_path) if config_path.is_file() else Config()

    def getenv(name: str) -> str | None:
        value = environ.get(name)
        return value if value not in (None, "") else None

    audit = config.audit
    overrides = {
        "idle_days": ("OSRM_IDLE_DAYS", int),
        "idle_cpu_percent": ("OSRM_IDLE_CPU_PERCENT", float),
        "oversized_cpu_percent": ("OSRM_OVERSIZED_CPU_PERCENT", float),
        "oversized_min_vcpus": ("OSRM_OVERSIZED_MIN_VCPUS", int),
        "orphan_volume_days": ("OSRM_ORPHAN_VOLUME_DAYS", int),
        "unused_ip_days": ("OSRM_UNUSED_IP_DAYS", int),
    }
    for field_name, (env_name, cast) in overrides.items():
        raw = getenv(env_name)
        if raw is not None:
            audit = replace(audit, **{field_name: cast(raw)})

    return replace(
        config,
        backend=getenv("OSRM_BACKEND") or config.backend,
        cloud=getenv("OS_CLOUD") or getenv("OSRM_CLOUD") or config.cloud,
        region=getenv("OS_REGION_NAME") or getenv("OSRM_REGION") or config.region,
        pricing=Path(getenv("OSRM_PRICING")).expanduser()
        if getenv("OSRM_PRICING")
        else config.pricing,
        audit=audit,
    )


def build_client(config: Config, now=None):
    """Instantiate the backend named in the config."""
    if config.backend == "fake":
        from .clients.fake import FakeCloudClient

        return FakeCloudClient(now=now)
    if config.backend == "openstack":
        from .clients.openstack import OpenStackClient

        return OpenStackClient(cloud=config.cloud, region=config.region)
    raise ValueError(f"unknown backend {config.backend!r} (expected 'fake' or 'openstack')")
