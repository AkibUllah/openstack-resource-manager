"""Find waste: idle/oversized servers, orphaned volumes, unused floating IPs, broken resources."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from .clients.base import CloudClient
from .config import AuditThresholds
from .models import ServerStatus, VolumeStatus, utcnow
from .pricing import ZERO, PriceTable, money


@dataclass(frozen=True)
class Finding:
    kind: str  # idle_server | oversized_server | orphaned_volume | unused_floating_ip | error_state
    severity: str  # low | medium | high
    resource_type: str
    resource_id: str
    name: str
    project_id: str
    message: str
    monthly_saving: Decimal = ZERO
    recommendation: str = ""

    def to_row(self) -> dict:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "name": self.name,
            "project_id": self.project_id,
            "message": self.message,
            "monthly_saving": str(money(self.monthly_saving)),
            "recommendation": self.recommendation,
        }


@dataclass
class AuditReport:
    findings: list[Finding] = field(default_factory=list)
    currency: str = "BDT"
    scanned: dict[str, int] = field(default_factory=dict)

    @property
    def total_monthly_saving(self) -> Decimal:
        return sum((f.monthly_saving for f in self.findings), ZERO)

    def by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in self.findings:
            counts[f.kind] = counts.get(f.kind, 0) + 1
        return dict(sorted(counts.items()))

    def filter(
        self, kinds: set[str] | None = None, min_severity: str | None = None
    ) -> list[Finding]:
        order = {"low": 0, "medium": 1, "high": 2}
        out = self.findings
        if kinds:
            out = [f for f in out if f.kind in kinds]
        if min_severity:
            out = [f for f in out if order[f.severity] >= order[min_severity]]
        return out


def run_audit(
    client: CloudClient,
    table: PriceTable,
    thresholds: AuditThresholds | None = None,
    project_id: str | None = None,
    now: datetime | None = None,
) -> AuditReport:
    t = thresholds or AuditThresholds()
    now = now or getattr(client, "now", None) or utcnow()
    hours = table.hours_per_month
    flavors = {f.id: f for f in client.list_flavors()}
    report = AuditReport(currency=table.currency)

    servers = client.list_servers(project_id)
    volumes = client.list_volumes(project_id)
    fips = client.list_floating_ips(project_id)
    report.scanned = {"servers": len(servers), "volumes": len(volumes), "floating_ips": len(fips)}

    for s in servers:
        flavor = flavors.get(s.flavor_id)
        full_price, _ = table.flavor_hourly(flavor)
        metrics = client.get_server_metrics(s.id)

        if s.status is ServerStatus.SHUTOFF and s.days_since_update(now) >= t.idle_days:
            days = int(s.days_since_update(now))
            # Compute is (usually) free while stopped; the saving is the attached storage.
            attached = [v for v in volumes if s.id in v.attached_to]
            saving = sum((table.volume_hourly(v) for v in attached), ZERO) * hours
            report.findings.append(
                Finding(
                    "idle_server",
                    "medium" if days < 90 else "high",
                    "server",
                    s.id,
                    s.name,
                    s.project_id,
                    f"SHUTOFF for {days} days",
                    saving,
                    "Snapshot and delete, or document why it must stay",
                )
            )
        elif s.status is ServerStatus.ACTIVE and metrics is not None:
            if metrics.cpu_percent < t.idle_cpu_percent:
                report.findings.append(
                    Finding(
                        "idle_server",
                        "medium",
                        "server",
                        s.id,
                        s.name,
                        s.project_id,
                        f"ACTIVE at {metrics.cpu_percent:.1f}% average CPU",
                        full_price * hours,
                        "Stop or delete if nobody claims it",
                    )
                )
            elif (
                flavor is not None
                and flavor.vcpus >= t.oversized_min_vcpus
                and metrics.cpu_percent < t.oversized_cpu_percent
            ):
                # Assume a flavor half the size would do: saving = half the compute bill.
                report.findings.append(
                    Finding(
                        "oversized_server",
                        "low",
                        "server",
                        s.id,
                        s.name,
                        s.project_id,
                        f"{flavor.name} ({flavor.vcpus} vCPU) at {metrics.cpu_percent:.1f}% CPU",
                        full_price * hours / 2,
                        "Resize to a flavor with half the vCPUs",
                    )
                )
        if s.status is ServerStatus.ERROR:
            report.findings.append(
                Finding(
                    "error_state",
                    "high",
                    "server",
                    s.id,
                    s.name,
                    s.project_id,
                    f"server in ERROR for {int(s.days_since_update(now))} days",
                    ZERO,
                    "Rebuild or delete; it may still hold quota",
                )
            )

    for v in volumes:
        age = (now - v.created_at).total_seconds() / 86400
        if v.is_orphaned and age >= t.orphan_volume_days:
            report.findings.append(
                Finding(
                    "orphaned_volume",
                    "medium" if v.size_gb < 200 else "high",
                    "volume",
                    v.id,
                    v.name,
                    v.project_id,
                    f"{v.size_gb} GB available, unattached for {int(age)} days",
                    table.volume_hourly(v) * hours,
                    "Snapshot to object storage and delete",
                )
            )
        elif v.status is VolumeStatus.ERROR:
            report.findings.append(
                Finding(
                    "error_state",
                    "medium",
                    "volume",
                    v.id,
                    v.name,
                    v.project_id,
                    f"volume in {v.status.value} state",
                    table.volume_hourly(v) * hours,
                    "Reset state or delete",
                )
            )

    for f in fips:
        age = (now - f.created_at).total_seconds() / 86400
        if f.is_unused and age >= t.unused_ip_days:
            report.findings.append(
                Finding(
                    "unused_floating_ip",
                    "low",
                    "floating_ip",
                    f.id,
                    f.address,
                    f.project_id,
                    f"not attached to any port for {int(age)} days",
                    table.floating_ip_hour * hours,
                    "Release it",
                )
            )

    severity_rank = {"high": 0, "medium": 1, "low": 2}
    report.findings.sort(key=lambda x: (severity_rank[x.severity], -x.monthly_saving, x.name))
    return report
