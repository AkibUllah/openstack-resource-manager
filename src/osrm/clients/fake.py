"""In-memory cloud with realistic fixture data: three projects of a Dhaka-hosted OpenStack cloud.

Used for tests, demos and dry-runs. Mutating calls (start/stop/delete) change the in-memory state
exactly as the real cloud would, so the CLI behaves identically against either backend.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from ..exceptions import InvalidState, NotFound
from ..models import (
    Flavor,
    FloatingIP,
    Image,
    Network,
    Project,
    Server,
    ServerMetrics,
    ServerStatus,
    Volume,
    VolumeStatus,
)

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def _ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


PROJECTS = [
    Project("p-pathao-prod", "pathao-prod", "Ride-hailing production workloads"),
    Project("p-chaldal-staging", "chaldal-staging", "Grocery platform staging + CI runners"),
    Project("p-bkash-sandbox", "bkash-sandbox", "Payment integration sandbox"),
]

FLAVORS = [
    Flavor("f-1", "m1.small", vcpus=1, ram_mb=2048, disk_gb=20),
    Flavor("f-2", "m1.medium", vcpus=2, ram_mb=4096, disk_gb=40),
    Flavor("f-3", "m1.large", vcpus=4, ram_mb=8192, disk_gb=80),
    Flavor("f-4", "m1.xlarge", vcpus=8, ram_mb=16384, disk_gb=160),
    Flavor("f-5", "c2.highcpu", vcpus=16, ram_mb=32768, disk_gb=100),
]

IMAGES = [
    Image("img-1", "ubuntu-22.04", size_bytes=640 * 1024**2, min_disk_gb=10, min_ram_mb=512),
    Image("img-2", "ubuntu-24.04", size_bytes=700 * 1024**2, min_disk_gb=10, min_ram_mb=512),
    Image("img-3", "debian-12", size_bytes=560 * 1024**2, min_disk_gb=8, min_ram_mb=512),
    Image("img-4", "rockylinux-9", size_bytes=1100 * 1024**2, min_disk_gb=10, min_ram_mb=1024),
]

NETWORKS = [
    Network("net-ext", "public", project_id="p-admin", external=True, subnets=("103.120.8.0/24",)),
    Network("net-pathao", "pathao-internal", "p-pathao-prod", subnets=("10.10.0.0/20",)),
    Network("net-chaldal", "chaldal-staging-net", "p-chaldal-staging", subnets=("10.20.0.0/22",)),
    Network("net-bkash", "bkash-sandbox-net", "p-bkash-sandbox", subnets=("10.30.0.0/24",)),
]


def _server(sid, name, status, flavor, image, project, created_days, updated_days, ip, meta=None):
    return Server(
        id=sid,
        name=name,
        status=status,
        flavor_id=flavor,
        image_id=image,
        project_id=project,
        created_at=_ago(created_days),
        updated_at=_ago(updated_days),
        addresses={"internal": [ip]},
        metadata=meta or {},
    )


SERVERS = [
    # pathao-prod: busy API tier, one oversized DB box, one forgotten SHUTOFF worker
    _server(
        "srv-01",
        "api-1",
        ServerStatus.ACTIVE,
        "f-3",
        "img-2",
        "p-pathao-prod",
        210,
        2,
        "10.10.0.11",
        {"role": "api", "env": "prod"},
    ),
    _server(
        "srv-02",
        "api-2",
        ServerStatus.ACTIVE,
        "f-3",
        "img-2",
        "p-pathao-prod",
        210,
        2,
        "10.10.0.12",
        {"role": "api", "env": "prod"},
    ),
    _server(
        "srv-03",
        "db-primary",
        ServerStatus.ACTIVE,
        "f-5",
        "img-1",
        "p-pathao-prod",
        400,
        1,
        "10.10.0.20",
        {"role": "db"},
    ),
    _server(
        "srv-04",
        "worker-old",
        ServerStatus.SHUTOFF,
        "f-2",
        "img-1",
        "p-pathao-prod",
        300,
        45,
        "10.10.0.31",
        {"role": "worker"},
    ),
    _server(
        "srv-05",
        "cache-1",
        ServerStatus.ACTIVE,
        "f-2",
        "img-2",
        "p-pathao-prod",
        150,
        3,
        "10.10.0.40",
        {"role": "cache"},
    ),
    # chaldal-staging: CI runners, one stopped last week (not idle yet), one ERROR box
    _server(
        "srv-06",
        "ci-runner-1",
        ServerStatus.ACTIVE,
        "f-3",
        "img-3",
        "p-chaldal-staging",
        90,
        1,
        "10.20.0.5",
        {"role": "ci"},
    ),
    _server(
        "srv-07",
        "ci-runner-2",
        ServerStatus.ACTIVE,
        "f-3",
        "img-3",
        "p-chaldal-staging",
        90,
        1,
        "10.20.0.6",
        {"role": "ci"},
    ),
    _server(
        "srv-08",
        "staging-web",
        ServerStatus.SHUTOFF,
        "f-2",
        "img-2",
        "p-chaldal-staging",
        60,
        6,
        "10.20.0.7",
    ),
    _server(
        "srv-09",
        "broken-import",
        ServerStatus.ERROR,
        "f-1",
        "img-4",
        "p-chaldal-staging",
        20,
        20,
        "10.20.0.8",
    ),
    # bkash-sandbox: tiny boxes, one xlarge "load test" machine barely used
    _server(
        "srv-10",
        "sandbox-api",
        ServerStatus.ACTIVE,
        "f-1",
        "img-2",
        "p-bkash-sandbox",
        120,
        4,
        "10.30.0.10",
    ),
    _server(
        "srv-11",
        "loadtest-01",
        ServerStatus.ACTIVE,
        "f-4",
        "img-1",
        "p-bkash-sandbox",
        75,
        30,
        "10.30.0.11",
        {"owner": "qa"},
    ),
    _server(
        "srv-12",
        "legacy-sim",
        ServerStatus.SHUTOFF,
        "f-2",
        "img-1",
        "p-bkash-sandbox",
        500,
        120,
        "10.30.0.12",
    ),
]

METRICS = {
    "srv-01": ServerMetrics(cpu_percent=48.0, net_rx_mbps=120.0, net_tx_mbps=95.0),
    "srv-02": ServerMetrics(cpu_percent=51.5, net_rx_mbps=118.0, net_tx_mbps=90.0),
    "srv-03": ServerMetrics(cpu_percent=6.5, net_rx_mbps=20.0, net_tx_mbps=18.0),  # 16 vCPU at 6.5%
    "srv-05": ServerMetrics(cpu_percent=22.0, net_rx_mbps=30.0, net_tx_mbps=28.0),
    "srv-06": ServerMetrics(cpu_percent=35.0, net_rx_mbps=10.0, net_tx_mbps=8.0),
    "srv-07": ServerMetrics(cpu_percent=1.2, net_rx_mbps=0.1, net_tx_mbps=0.1),  # idle runner
    "srv-10": ServerMetrics(cpu_percent=9.0, net_rx_mbps=2.0, net_tx_mbps=1.5),
    "srv-11": ServerMetrics(cpu_percent=2.0, net_rx_mbps=0.3, net_tx_mbps=0.2),  # 8 vCPU at 2%
}

VOLUMES = [
    Volume(
        "vol-01",
        "api-1-root",
        80,
        VolumeStatus.IN_USE,
        "p-pathao-prod",
        _ago(210),
        ("srv-01",),
        bootable=True,
    ),
    Volume(
        "vol-02",
        "api-2-root",
        80,
        VolumeStatus.IN_USE,
        "p-pathao-prod",
        _ago(210),
        ("srv-02",),
        bootable=True,
    ),
    Volume("vol-03", "db-data", 500, VolumeStatus.IN_USE, "p-pathao-prod", _ago(400), ("srv-03",)),
    Volume("vol-04", "db-backup-2025-12", 500, VolumeStatus.AVAILABLE, "p-pathao-prod", _ago(300)),
    Volume(
        "vol-05",
        "worker-old-root",
        40,
        VolumeStatus.IN_USE,
        "p-pathao-prod",
        _ago(300),
        ("srv-04",),
        bootable=True,
    ),
    Volume(
        "vol-06", "ci-cache", 200, VolumeStatus.IN_USE, "p-chaldal-staging", _ago(90), ("srv-06",)
    ),
    Volume("vol-07", "scratch", 100, VolumeStatus.AVAILABLE, "p-chaldal-staging", _ago(40)),
    Volume("vol-08", "tmp-restore-test", 50, VolumeStatus.AVAILABLE, "p-chaldal-staging", _ago(3)),
    Volume(
        "vol-09", "sandbox-data", 20, VolumeStatus.IN_USE, "p-bkash-sandbox", _ago(120), ("srv-10",)
    ),
    Volume("vol-10", "loadtest-results", 250, VolumeStatus.AVAILABLE, "p-bkash-sandbox", _ago(60)),
    Volume("vol-11", "stuck-volume", 10, VolumeStatus.ERROR, "p-bkash-sandbox", _ago(15)),
]

FLOATING_IPS = [
    FloatingIP(
        "fip-01",
        "103.120.8.10",
        "p-pathao-prod",
        _ago(210),
        "net-ext",
        port_id="port-01",
        server_id="srv-01",
        status="ACTIVE",
    ),
    FloatingIP(
        "fip-02",
        "103.120.8.11",
        "p-pathao-prod",
        _ago(210),
        "net-ext",
        port_id="port-02",
        server_id="srv-02",
        status="ACTIVE",
    ),
    FloatingIP("fip-03", "103.120.8.12", "p-pathao-prod", _ago(100), "net-ext"),
    FloatingIP(
        "fip-04",
        "103.120.8.20",
        "p-chaldal-staging",
        _ago(90),
        "net-ext",
        port_id="port-06",
        server_id="srv-06",
        status="ACTIVE",
    ),
    FloatingIP("fip-05", "103.120.8.21", "p-chaldal-staging", _ago(60), "net-ext"),
    FloatingIP("fip-06", "103.120.8.22", "p-chaldal-staging", _ago(2), "net-ext"),
    FloatingIP(
        "fip-07",
        "103.120.8.30",
        "p-bkash-sandbox",
        _ago(120),
        "net-ext",
        port_id="port-10",
        server_id="srv-10",
        status="ACTIVE",
    ),
    FloatingIP("fip-08", "103.120.8.31", "p-bkash-sandbox", _ago(75), "net-ext"),
]


class FakeCloudClient:
    name = "fake"

    def __init__(self, now: datetime | None = None) -> None:
        self.now = now or NOW
        self._projects = {p.id: p for p in PROJECTS}
        self._flavors = {f.id: f for f in FLAVORS}
        self._images = {i.id: i for i in IMAGES}
        self._networks = {n.id: n for n in NETWORKS}
        self._servers = {s.id: s for s in SERVERS}
        self._volumes = {v.id: v for v in VOLUMES}
        self._fips = {f.id: f for f in FLOATING_IPS}
        self._metrics = dict(METRICS)
        self.calls: list[tuple[str, str]] = []  # (operation, resource id) for assertions

    # ------------------------------------------------------------------ identity / compute

    def list_projects(self) -> list[Project]:
        return sorted(self._projects.values(), key=lambda p: p.name)

    def list_servers(self, project_id: str | None = None) -> list[Server]:
        servers = self._servers.values()
        if project_id:
            servers = [s for s in servers if s.project_id == project_id]
        return sorted(servers, key=lambda s: (s.project_id, s.name))

    def get_server(self, server_id: str) -> Server:
        server = self._servers.get(server_id)
        if server is None:
            # Allow lookup by name as a convenience, like the openstack CLI.
            matches = [s for s in self._servers.values() if s.name == server_id]
            if len(matches) == 1:
                return matches[0]
            raise NotFound("server", server_id)
        return server

    def start_server(self, server_id: str) -> Server:
        server = self.get_server(server_id)
        if server.status is ServerStatus.ACTIVE:
            raise InvalidState(f"server {server.name!r} is already ACTIVE")
        if server.status is ServerStatus.ERROR:
            raise InvalidState(f"server {server.name!r} is in ERROR state and cannot be started")
        updated = replace(server, status=ServerStatus.ACTIVE, updated_at=self.now)
        self._servers[server.id] = updated
        self.calls.append(("start", server.id))
        return updated

    def stop_server(self, server_id: str) -> Server:
        server = self.get_server(server_id)
        if server.status is not ServerStatus.ACTIVE:
            raise InvalidState(f"server {server.name!r} is {server.status.value}, not ACTIVE")
        updated = replace(server, status=ServerStatus.SHUTOFF, updated_at=self.now)
        self._servers[server.id] = updated
        self.calls.append(("stop", server.id))
        return updated

    def delete_server(self, server_id: str) -> None:
        server = self.get_server(server_id)
        del self._servers[server.id]
        # Detach volumes and release floating IPs the way nova/neutron would.
        for vid, vol in list(self._volumes.items()):
            if server.id in vol.attached_to:
                remaining = tuple(x for x in vol.attached_to if x != server.id)
                status = vol.status if remaining else VolumeStatus.AVAILABLE
                self._volumes[vid] = replace(vol, attached_to=remaining, status=status)
        for fid, fip in list(self._fips.items()):
            if fip.server_id == server.id:
                self._fips[fid] = replace(fip, port_id=None, server_id=None, status="DOWN")
        self._metrics.pop(server.id, None)
        self.calls.append(("delete", server.id))

    def list_flavors(self) -> list[Flavor]:
        return sorted(self._flavors.values(), key=lambda f: (f.vcpus, f.ram_mb))

    def list_images(self) -> list[Image]:
        return sorted(self._images.values(), key=lambda i: i.name)

    def get_server_metrics(self, server_id: str) -> ServerMetrics | None:
        return self._metrics.get(server_id)

    # ------------------------------------------------------------------ storage / network

    def list_volumes(self, project_id: str | None = None) -> list[Volume]:
        volumes = self._volumes.values()
        if project_id:
            volumes = [v for v in volumes if v.project_id == project_id]
        return sorted(volumes, key=lambda v: (v.project_id, v.name))

    def list_networks(self, project_id: str | None = None) -> list[Network]:
        networks = self._networks.values()
        if project_id:
            networks = [n for n in networks if n.project_id == project_id or n.external]
        return sorted(networks, key=lambda n: n.name)

    def list_floating_ips(self, project_id: str | None = None) -> list[FloatingIP]:
        fips = self._fips.values()
        if project_id:
            fips = [f for f in fips if f.project_id == project_id]
        return sorted(fips, key=lambda f: f.address)
