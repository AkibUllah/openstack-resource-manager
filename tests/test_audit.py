from __future__ import annotations

from decimal import Decimal

from osrm.audit import run_audit
from osrm.config import AuditThresholds
from osrm.pricing import money


def by_kind(report):
    out = {}
    for f in report.findings:
        out.setdefault(f.kind, set()).add(f.name)
    return out


def test_audit_finds_each_kind(client, table):
    report = run_audit(client, table)
    kinds = by_kind(report)
    # loadtest-01 runs at 2% CPU: below the idle threshold, so idle rather than oversized
    assert kinds["idle_server"] == {"worker-old", "legacy-sim", "ci-runner-2", "loadtest-01"}
    assert kinds["oversized_server"] == {"db-primary"}
    assert kinds["orphaned_volume"] == {
        "db-backup-2025-12",
        "scratch",
        "loadtest-results",
    }  # tmp-restore-test is 3 days old
    assert kinds["unused_floating_ip"] == {
        "103.120.8.12",
        "103.120.8.21",
        "103.120.8.31",
    }  # .22 is 2 days old
    assert kinds["error_state"] == {"broken-import", "stuck-volume"}
    assert report.scanned == {"servers": 12, "volumes": 11, "floating_ips": 8}


def test_savings_are_priced(client, table):
    report = run_audit(client, table)
    f = {x.name: x for x in report.findings}
    assert money(f["loadtest-results"].monthly_saving) == money(
        Decimal(250) * Decimal("0.0002") * 730
    )
    assert money(f["103.120.8.12"].monthly_saving) == Decimal("365.00")
    assert money(f["db-primary"].monthly_saving) == Decimal("13140.00")  # half of 36 * 730
    assert money(f["ci-runner-2"].monthly_saving) == Decimal("7300.00")  # idle active m1.large
    assert (
        f["worker-old"].monthly_saving == Decimal(40) * Decimal("0.0002") * 730
    )  # only its root volume
    assert f["broken-import"].monthly_saving == 0
    assert report.total_monthly_saving == sum(x.monthly_saving for x in report.findings)


def test_sorted_by_severity_then_saving(client, table):
    report = run_audit(client, table)
    severities = [f.severity for f in report.findings]
    rank = {"high": 0, "medium": 1, "low": 2}
    assert [rank[s] for s in severities] == sorted(rank[s] for s in severities)
    assert report.findings[0].severity == "high"


def test_thresholds_change_results(client, table):
    strict = AuditThresholds(
        idle_days=3, orphan_volume_days=1, unused_ip_days=1, oversized_min_vcpus=1
    )
    report = run_audit(client, table, strict)
    kinds = by_kind(report)
    assert "staging-web" in kinds["idle_server"]  # stopped 6 days ago
    assert "tmp-restore-test" in kinds["orphaned_volume"]
    assert "103.120.8.22" in kinds["unused_floating_ip"]
    assert "sandbox-api" in kinds["oversized_server"]  # 1 vCPU at 9% now counts

    relaxed = AuditThresholds(
        idle_days=365,
        idle_cpu_percent=0,
        oversized_cpu_percent=0,
        orphan_volume_days=365,
        unused_ip_days=365,
    )
    report = run_audit(client, table, relaxed)
    assert set(by_kind(report)) == {"error_state"}


def test_project_scope_and_filters(client, table):
    report = run_audit(client, table, project_id="p-bkash-sandbox")
    assert {f.project_id for f in report.findings} == {"p-bkash-sandbox"}
    only_high = report.filter(min_severity="high")
    assert all(f.severity == "high" for f in only_high)
    volumes = report.filter(kinds={"orphaned_volume"})
    assert [f.name for f in volumes] == ["loadtest-results"]
    assert report.by_kind()["unused_floating_ip"] == 1
