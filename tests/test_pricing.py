from __future__ import annotations

from decimal import Decimal

from osrm.models import Flavor
from osrm.pricing import PriceTable, estimate_costs, money

D = Decimal


def test_bundled_table_loads(table):
    assert table.currency == "BDT" and table.hours_per_month == 730
    assert table.flavors["m1.small"] == D("2.50")
    assert table.source == "bundled"


def test_flavor_pricing_exact_and_fallback(table):
    price, exact = table.flavor_hourly(Flavor("f", "m1.large", 4, 8192, 80))
    assert (price, exact) == (D("10.00"), True)
    price, exact = table.flavor_hourly(Flavor("f", "g1.gpu", 8, 65536, 200))
    assert exact is False
    assert price == D("8") * D("2.00") + D("64") * D("0.60")  # per-vCPU + per-GB-RAM fallback
    assert table.flavor_hourly(None) == (D("0"), False)


def test_stopped_servers_do_not_pay_for_compute(client, table):
    flavors = {f.id: f for f in client.list_flavors()}
    stopped = client.get_server("srv-04")  # SHUTOFF m1.medium
    running = client.get_server("srv-05")  # ACTIVE m1.medium
    assert table.server_hourly(stopped, flavors["f-2"])[0] == D("0")
    assert table.server_hourly(running, flavors["f-2"])[0] == D("5.00")


def test_estimate_totals_add_up(client, table):
    est = estimate_costs(client, table, project_id="p-rideshare-prod")
    # ACTIVE: api-1 + api-2 (m1.large 10 each) + db-primary (c2.highcpu 36) + cache-1 (m1.medium 5)
    servers = sum(ln.hourly for ln in est.lines if ln.resource_type == "server")
    assert servers == D("61.00")
    volumes = sum(ln.hourly for ln in est.lines if ln.resource_type == "volume")
    assert volumes == D(80 + 80 + 500 + 500 + 40) * D("0.0002")
    fips = sum(ln.hourly for ln in est.lines if ln.resource_type == "floating_ip")
    assert fips == D("1.50")
    assert est.hourly_total == servers + volumes + fips
    assert money(est.monthly_total) == money(est.hourly_total * 730) == D("45800.20")
    assert set(est.by_type()) == {"server", "volume", "floating_ip"}
    assert list(est.by_project()) == ["p-rideshare-prod"]
    assert est.unpriced == []


def test_custom_table_from_yaml(tmp_path, client):
    path = tmp_path / "usd.yaml"
    path.write_text(
        "currency: USD\nhours_per_month: 720\nflavors:\n  m1.small: 0.01\nfallback:\n"
        "  per_vcpu_hour: 0.02\n  per_ram_gb_hour: 0.005\n"
        "volume_gb_hour: 0.0001\nfloating_ip_hour: 0.005\n"
    )
    table = PriceTable.load(path)
    assert table.currency == "USD" and table.source == str(path)
    est = estimate_costs(client, table)
    assert est.currency == "USD" and est.hours_per_month == 720
    unpriced = {ln.detail.split(" · ")[0] for ln in est.unpriced}
    assert "m1.large" in unpriced and "m1.small" not in unpriced
