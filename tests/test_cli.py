from __future__ import annotations

import csv
import io
import json

from osrm import __version__

from .conftest import invoke


def test_version_and_help(runner, env):
    r = invoke(runner, env, "--version")
    assert r.exit_code == 0 and __version__ in r.output
    r = invoke(runner, env, "--help")
    assert r.exit_code == 0 and "audit" in r.output and "cost" in r.output


def test_servers_list_table_and_json(runner, env):
    r = invoke(runner, env, "servers", "list")
    assert r.exit_code == 0, r.output
    assert "Servers (12)" in r.output and "db-primary" in r.output and "c2.highcpu" in r.output

    r = invoke(
        runner,
        env,
        "servers",
        "list",
        "--project",
        "bkash-sandbox",
        "--status",
        "shutoff",
        "-f",
        "json",
    )
    assert r.exit_code == 0, r.output
    rows = json.loads(r.output)
    assert [row["name"] for row in rows] == ["legacy-sim"]
    assert rows[0]["project"] == "bkash-sandbox"


def test_servers_show(runner, env):
    r = invoke(runner, env, "servers", "show", "db-primary", "--format", "json")
    assert r.exit_code == 0, r.output
    detail = json.loads(r.output)
    assert detail["id"] == "srv-03"
    assert detail["flavor"]["name"] == "c2.highcpu"
    assert [v["name"] for v in detail["volumes"]] == ["db-data"]
    assert detail["metrics"]["cpu_percent"] == 6.5
    r = invoke(runner, env, "servers", "show", "ghost")
    assert r.exit_code == 1 and "not found" in r.output


def test_stop_dry_run_does_not_change_state(runner, env, shared_client):
    r = invoke(runner, env, "servers", "stop", "api-1", "--dry-run")
    assert r.exit_code == 0 and "dry-run" in r.output and "would stop" in r.output
    assert shared_client.get_server("srv-01").status.value == "ACTIVE"
    assert shared_client.calls == []


def test_stop_and_start_change_state(runner, env, shared_client):
    r = invoke(runner, env, "servers", "stop", "api-1")
    assert r.exit_code == 0 and "stopped" in r.output and "SHUTOFF" in r.output
    assert shared_client.get_server("srv-01").status.value == "SHUTOFF"
    r = invoke(runner, env, "servers", "stop", "api-1")
    assert r.exit_code == 1 and "not ACTIVE" in r.output
    r = invoke(runner, env, "servers", "start", "srv-01")
    assert r.exit_code == 0 and shared_client.get_server("srv-01").status.value == "ACTIVE"


def test_delete_requires_confirmation(runner, env, shared_client):
    r = invoke(runner, env, "servers", "delete", "worker-old", input="n\n")
    assert r.exit_code == 1 and "aborted" in r.output
    assert shared_client.get_server("srv-04")
    r = invoke(runner, env, "servers", "delete", "worker-old", "--yes")
    assert r.exit_code == 0 and "deleted" in r.output
    assert ("delete", "srv-04") in shared_client.calls
    assert all(s.id != "srv-04" for s in shared_client.list_servers())


def test_volumes_orphaned_and_ips_unused(runner, env):
    r = invoke(runner, env, "volumes", "list", "--orphaned", "-f", "json")
    assert r.exit_code == 0, r.output
    assert sorted(v["name"] for v in json.loads(r.output)) == [
        "db-backup-2025-12",
        "loadtest-results",
        "scratch",
        "tmp-restore-test",
    ]
    r = invoke(runner, env, "ips", "list", "--unused", "--project", "pathao-prod", "-f", "csv")
    assert r.exit_code == 0, r.output
    rows = list(csv.DictReader(io.StringIO(r.output)))
    assert [row["address"] for row in rows] == ["103.120.8.12"]


def test_audit_table_and_json(runner, env):
    r = invoke(runner, env, "audit")
    assert r.exit_code == 0, r.output
    assert (
        "Audit findings (13)" in r.output
        and "potential saving" in r.output
        and "BDT/month" in r.output
    )

    r = invoke(
        runner,
        env,
        "audit",
        "--format",
        "json",
        "--kind",
        "orphaned_volume",
        "--min-severity",
        "high",
    )
    assert r.exit_code == 0, r.output
    payload = json.loads(r.output)
    assert payload["scanned"]["servers"] == 12
    assert [f["name"] for f in payload["findings"]] == ["db-backup-2025-12", "loadtest-results"]
    assert payload["total_monthly_saving"] == "109.50"


def test_cost_estimate(runner, env):
    r = invoke(runner, env, "cost", "estimate", "--project", "pathao-prod")
    assert r.exit_code == 0, r.output
    assert "45800.20 BDT/month" in r.output and "pathao-prod" in r.output

    r = invoke(runner, env, "cost", "estimate", "--format", "json", "--detail")
    assert r.exit_code == 0, r.output
    payload = json.loads(r.output)
    assert payload["currency"] == "BDT" and set(payload["by_project"]) == {
        "pathao-prod",
        "chaldal-staging",
        "bkash-sandbox",
    }
    assert len(payload["lines"]) == 12 + 11 + 8
    assert payload["unpriced_flavors"] == []


def test_cost_estimate_with_custom_pricing(runner, env, tmp_path):
    pricing = tmp_path / "p.yaml"
    pricing.write_text(
        "currency: USD\nflavors:\n  m1.small: 0.01\n"
        "fallback:\n  per_vcpu_hour: 0.02\n  per_ram_gb_hour: 0\n"
    )
    r = invoke(
        runner, env, "cost", "estimate", "--pricing", str(pricing), "--project", "bkash-sandbox"
    )
    assert r.exit_code == 0, r.output
    assert (
        "USD/month" in r.output
        and "no exact price for flavors" in r.output
        and "m1.xlarge" in r.output
    )


def test_export_to_file_and_stdout(runner, env, tmp_path):
    out = tmp_path / "inventory.json"
    r = invoke(runner, env, "export", "--output", str(out))
    assert r.exit_code == 0 and "wrote" in r.output
    data = json.loads(out.read_text())
    assert set(data) == {"servers", "volumes", "ips", "flavors", "images", "projects"}
    assert len(data["servers"]) == 12

    r = invoke(runner, env, "export", "--resource", "flavors", "--format", "csv")
    assert r.exit_code == 0
    rows = list(csv.DictReader(io.StringIO(r.output)))
    assert [row["name"] for row in rows][:2] == ["m1.small", "m1.medium"]

    r = invoke(runner, env, "export", "--resource", "servers", "--format", "table")
    assert r.exit_code == 0 and "db-primary" in r.output
    r = invoke(runner, env, "export", "--resource", "unicorns")
    assert r.exit_code == 2


def test_projects_and_bad_inputs(runner, env):
    r = invoke(runner, env, "projects", "-f", "json")
    assert [p["name"] for p in json.loads(r.output)] == [
        "bkash-sandbox",
        "chaldal-staging",
        "pathao-prod",
    ]
    r = invoke(runner, env, "servers", "list", "--project", "nope")
    assert r.exit_code == 2 and "not found" in r.output
    r = invoke(runner, env, "servers", "list", "--format", "xml")
    assert r.exit_code == 2


def test_config_file_flag_and_env_thresholds(runner, env, tmp_path):
    cfg = tmp_path / "osrm.toml"
    cfg.write_text(
        'backend = "fake"\n[audit]\nidle_days = 3\norphan_volume_days = 1\nunused_ip_days = 1\n'
    )
    r = invoke(runner, env, "--config", str(cfg), "audit", "-f", "json")
    assert r.exit_code == 0, r.output
    names = {f["name"] for f in json.loads(r.output)["findings"]}
    assert {"staging-web", "tmp-restore-test", "103.120.8.22"} <= names

    r = invoke(
        runner,
        {**env, "OSRM_IDLE_DAYS": "365", "OSRM_IDLE_CPU_PERCENT": "0"},
        "audit",
        "-f",
        "json",
        "--kind",
        "idle_server",
    )
    assert r.exit_code == 0 and json.loads(r.output)["findings"] == []


def test_openstack_backend_without_sdk_fails_cleanly(runner, env):
    r = invoke(runner, {**env, "OSRM_BACKEND": "openstack"}, "servers", "list")
    assert r.exit_code == 1
    assert "openstacksdk is not installed" in r.output
