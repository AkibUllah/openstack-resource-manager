"""Backend-neutral resource models. Every client (real or fake) returns these."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ServerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SHUTOFF = "SHUTOFF"
    ERROR = "ERROR"
    BUILD = "BUILD"
    PAUSED = "PAUSED"
    SUSPENDED = "SUSPENDED"


class VolumeStatus(str, Enum):
    AVAILABLE = "available"
    IN_USE = "in-use"
    ERROR = "error"
    CREATING = "creating"


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    description: str = ""
    enabled: bool = True


@dataclass(frozen=True)
class Flavor:
    id: str
    name: str
    vcpus: int
    ram_mb: int
    disk_gb: int

    @property
    def ram_gb(self) -> float:
        return self.ram_mb / 1024


@dataclass(frozen=True)
class Image:
    id: str
    name: str
    status: str = "active"
    size_bytes: int = 0
    min_disk_gb: int = 0
    min_ram_mb: int = 0
    visibility: str = "public"


@dataclass(frozen=True)
class ServerMetrics:
    """Averages over the lookback window (typically 7 days)."""

    cpu_percent: float
    net_rx_mbps: float = 0.0
    net_tx_mbps: float = 0.0


@dataclass(frozen=True)
class Server:
    id: str
    name: str
    status: ServerStatus
    flavor_id: str
    image_id: str | None
    project_id: str
    created_at: datetime
    updated_at: datetime
    addresses: dict[str, list[str]] = field(default_factory=dict)
    metadata: dict[str, str] = field(default_factory=dict)
    availability_zone: str = "nova"

    @property
    def is_running(self) -> bool:
        return self.status is ServerStatus.ACTIVE

    def age_days(self, now: datetime) -> float:
        return (now - self.created_at).total_seconds() / 86400

    def days_since_update(self, now: datetime) -> float:
        return (now - self.updated_at).total_seconds() / 86400


@dataclass(frozen=True)
class Volume:
    id: str
    name: str
    size_gb: int
    status: VolumeStatus
    project_id: str
    created_at: datetime
    attached_to: tuple[str, ...] = ()  # server ids
    volume_type: str = "ssd"
    bootable: bool = False

    @property
    def is_orphaned(self) -> bool:
        return self.status is VolumeStatus.AVAILABLE and not self.attached_to


@dataclass(frozen=True)
class Network:
    id: str
    name: str
    project_id: str
    external: bool = False
    subnets: tuple[str, ...] = ()


@dataclass(frozen=True)
class FloatingIP:
    id: str
    address: str
    project_id: str
    created_at: datetime
    network_id: str
    port_id: str | None = None
    server_id: str | None = None
    status: str = "DOWN"

    @property
    def is_unused(self) -> bool:
        return self.port_id is None and self.server_id is None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_row(obj) -> dict:
    """Flatten a dataclass into JSON/CSV-friendly primitives."""
    row = asdict(obj)
    for key, value in list(row.items()):
        if isinstance(value, Enum):
            row[key] = value.value
        elif isinstance(value, datetime):
            row[key] = value.isoformat()
        elif isinstance(value, tuple):
            row[key] = list(value)
    return row
