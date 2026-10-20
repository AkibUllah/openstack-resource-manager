"""Cost estimation from a YAML price table. Decimal everywhere."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from importlib import resources
from pathlib import Path

import yaml

from .clients.base import CloudClient
from .models import Flavor, FloatingIP, Server, ServerStatus, Volume

ZERO = Decimal("0")
MONEY = Decimal("0.01")


def D(value) -> Decimal:  # noqa: N802
    return value if isinstance(value, Decimal) else Decimal(str(value))


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PriceTable:
    currency: str
    hours_per_month: int
    flavors: dict[str, Decimal]
    per_vcpu_hour: Decimal
    per_ram_gb_hour: Decimal
    volume_gb_hour: Decimal
    floating_ip_hour: Decimal
    stopped_server_discount: Decimal
    source: str = "bundled"

    @classmethod
    def load(cls, path: Path | None = None) -> PriceTable:
        if path is None:
            text = resources.files("osrm.data").joinpath("pricing.yaml").read_text(encoding="utf-8")
            source = "bundled"
        else:
            text = Path(path).read_text(encoding="utf-8")
            source = str(path)
        return cls.from_dict(yaml.safe_load(text) or {}, source=source)

    @classmethod
    def from_dict(cls, data: dict, source: str = "inline") -> PriceTable:
        fallback = data.get("fallback") or {}
        return cls(
            currency=str(data.get("currency", "USD")),
            hours_per_month=int(data.get("hours_per_month", 730)),
            flavors={str(k): D(v) for k, v in (data.get("flavors") or {}).items()},
            per_vcpu_hour=D(fallback.get("per_vcpu_hour", 0)),
            per_ram_gb_hour=D(fallback.get("per_ram_gb_hour", 0)),
            volume_gb_hour=D(data.get("volume_gb_hour", 0)),
            floating_ip_hour=D(data.get("floating_ip_hour", 0)),
            stopped_server_discount=D(data.get("stopped_server_discount", 1)),
            source=source,
        )

    def flavor_hourly(self, flavor: Flavor | None) -> tuple[Decimal, bool]:
        """(price per hour, was it an exact flavor match)."""
        if flavor is None:
            return ZERO, False
        if flavor.name in self.flavors:
            return self.flavors[flavor.name], True
        estimate = D(flavor.vcpus) * self.per_vcpu_hour + D(flavor.ram_gb) * self.per_ram_gb_hour
        return estimate, False

    def server_hourly(self, server: Server, flavor: Flavor | None) -> tuple[Decimal, bool]:
        price, exact = self.flavor_hourly(flavor)
        if server.status is not ServerStatus.ACTIVE:
            price = price * (Decimal(1) - self.stopped_server_discount)
        return price, exact

    def volume_hourly(self, volume: Volume) -> Decimal:
        return D(volume.size_gb) * self.volume_gb_hour

    def floating_ip_hourly(self, fip: FloatingIP) -> Decimal:
        return self.floating_ip_hour


@dataclass
class CostLine:
    resource_type: str  # server | volume | floating_ip
    resource_id: str
    name: str
    project_id: str
    detail: str
    hourly: Decimal
    exact_price: bool = True

    @property
    def daily(self) -> Decimal:
        return self.hourly * 24

    def monthly(self, hours_per_month: int) -> Decimal:
        return self.hourly * hours_per_month

    def to_row(self, hours_per_month: int) -> dict:
        return {
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "name": self.name,
            "project_id": self.project_id,
            "detail": self.detail,
            "hourly": str(money(self.hourly)),
            "daily": str(money(self.daily)),
            "monthly": str(money(self.monthly(hours_per_month))),
            "exact_price": self.exact_price,
        }


@dataclass
class CostEstimate:
    currency: str
    hours_per_month: int
    lines: list[CostLine] = field(default_factory=list)

    @property
    def hourly_total(self) -> Decimal:
        return sum((ln.hourly for ln in self.lines), ZERO)

    @property
    def monthly_total(self) -> Decimal:
        return self.hourly_total * self.hours_per_month

    def by_project(self) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = {}
        for ln in self.lines:
            totals[ln.project_id] = totals.get(ln.project_id, ZERO) + ln.monthly(
                self.hours_per_month
            )
        return dict(sorted(totals.items()))

    def by_type(self) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = {}
        for ln in self.lines:
            totals[ln.resource_type] = totals.get(ln.resource_type, ZERO) + ln.monthly(
                self.hours_per_month
            )
        return dict(sorted(totals.items()))

    @property
    def unpriced(self) -> list[CostLine]:
        return [ln for ln in self.lines if not ln.exact_price]


def estimate_costs(
    client: CloudClient, table: PriceTable, project_id: str | None = None
) -> CostEstimate:
    flavors = {f.id: f for f in client.list_flavors()}
    estimate = CostEstimate(currency=table.currency, hours_per_month=table.hours_per_month)

    for server in client.list_servers(project_id):
        flavor = flavors.get(server.flavor_id)
        hourly, exact = table.server_hourly(server, flavor)
        detail = f"{flavor.name if flavor else server.flavor_id} · {server.status.value}"
        estimate.lines.append(
            CostLine("server", server.id, server.name, server.project_id, detail, hourly, exact)
        )
    for volume in client.list_volumes(project_id):
        detail = f"{volume.size_gb} GB · {volume.status.value}" + (
            " · orphaned" if volume.is_orphaned else ""
        )
        estimate.lines.append(
            CostLine(
                "volume",
                volume.id,
                volume.name,
                volume.project_id,
                detail,
                table.volume_hourly(volume),
            )
        )
    for fip in client.list_floating_ips(project_id):
        detail = fip.address + (" · unused" if fip.is_unused else f" · {fip.server_id}")
        estimate.lines.append(
            CostLine(
                "floating_ip",
                fip.id,
                fip.address,
                fip.project_id,
                detail,
                table.floating_ip_hourly(fip),
            )
        )
    return estimate
