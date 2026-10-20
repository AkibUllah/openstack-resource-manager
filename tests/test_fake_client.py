from __future__ import annotations

import pytest

from osrm.exceptions import InvalidState, NotFound
from osrm.models import ServerStatus, VolumeStatus


def test_fixtures_are_internally_consistent(client):
    projects = {p.id for p in client.list_projects()}
    flavors = {f.id for f in client.list_flavors()}
    images = {i.id for i in client.list_images()}
    servers = client.list_servers()
    assert len(servers) == 12
    for s in servers:
        assert s.project_id in projects and s.flavor_id in flavors and s.image_id in images
    server_ids = {s.id for s in servers}
    for v in client.list_volumes():
        assert v.project_id in projects
        assert set(v.attached_to) <= server_ids
    for f in client.list_floating_ips():
        assert f.project_id in projects
        assert f.server_id is None or f.server_id in server_ids


def test_project_filter_and_name_lookup(client):
    prod = client.list_servers("p-pathao-prod")
    assert {s.project_id for s in prod} == {"p-pathao-prod"} and len(prod) == 5
    assert client.get_server("db-primary").id == "srv-03"
    with pytest.raises(NotFound):
        client.get_server("does-not-exist")


def test_stop_start_transitions(client):
    stopped = client.stop_server("srv-01")
    assert stopped.status is ServerStatus.SHUTOFF and stopped.updated_at == client.now
    with pytest.raises(InvalidState):
        client.stop_server("srv-01")
    started = client.start_server("srv-01")
    assert started.status is ServerStatus.ACTIVE
    with pytest.raises(InvalidState):
        client.start_server("srv-01")
    with pytest.raises(InvalidState):
        client.start_server("srv-09")  # ERROR state
    assert client.calls == [("stop", "srv-01"), ("start", "srv-01")]


def test_delete_detaches_volumes_and_releases_ips(client):
    client.delete_server("srv-01")
    with pytest.raises(NotFound):
        client.get_server("srv-01")
    root = next(v for v in client.list_volumes() if v.id == "vol-01")
    assert root.status is VolumeStatus.AVAILABLE and root.attached_to == () and root.is_orphaned
    fip = next(f for f in client.list_floating_ips() if f.id == "fip-01")
    assert fip.is_unused and fip.status == "DOWN"
    assert client.get_server_metrics("srv-01") is None


def test_orphaned_and_unused_helpers(client):
    orphaned = {v.id for v in client.list_volumes() if v.is_orphaned}
    assert orphaned == {"vol-04", "vol-07", "vol-08", "vol-10"}
    unused = {f.address for f in client.list_floating_ips() if f.is_unused}
    assert unused == {"103.120.8.12", "103.120.8.21", "103.120.8.22", "103.120.8.31"}
    assert [n.name for n in client.list_networks("p-bkash-sandbox")] == [
        "bkash-sandbox-net",
        "public",
    ]
