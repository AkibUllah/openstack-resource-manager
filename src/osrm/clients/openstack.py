"""Real backend on top of openstacksdk. The SDK is imported lazily so the package installs and the
fake backend works without it (``pip install openstack-resource-manager[openstack]`` adds it).

Authentication follows the standard clouds.yaml lookup (``./clouds.yaml``, ``~/.config/openstack``,
``/etc/openstack``) plus ``OS_*`` environment variables, exactly like the ``openstack`` CLI.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..exceptions import BackendUnavailable, InvalidState, NotFound
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


def _parse_dt(value) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _status(value: str | None) -> ServerStatus:
    try:
        return ServerStatus((value or "").upper())
    except ValueError:
        return ServerStatus.ERROR


def _volume_status(value: str | None) -> VolumeStatus:
    try:
        return VolumeStatus((value or "").lower())
    except ValueError:
        return VolumeStatus.ERROR


class OpenStackClient:
    name = "openstack"

    def __init__(
        self, cloud: str | None = None, region: str | None = None, all_projects: bool = True
    ):
        try:
            import openstack  # noqa: F401
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise BackendUnavailable(
                "openstacksdk is not installed; "
                "run `pip install openstack-resource-manager[openstack]`"
            ) from exc
        import openstack

        self._conn = openstack.connect(cloud=cloud, region_name=region)
        self.cloud = cloud
        self.all_projects = all_projects

    # ------------------------------------------------------------------ mapping helpers

    @staticmethod
    def _flavor_id(server) -> str:
        flavor = getattr(server, "flavor", None) or {}
        return str(flavor.get("id") or flavor.get("original_name") or flavor.get("name") or "")

    @staticmethod
    def _addresses(server) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for net, entries in (getattr(server, "addresses", None) or {}).items():
            out[net] = [e.get("addr") for e in entries if e.get("addr")]
        return out

    def _map_server(self, s) -> Server:
        image = getattr(s, "image", None) or {}
        return Server(
            id=s.id,
            name=s.name,
            status=_status(s.status),
            flavor_id=self._flavor_id(s),
            image_id=image.get("id") if isinstance(image, dict) else None,
            project_id=getattr(s, "project_id", "") or "",
            created_at=_parse_dt(getattr(s, "created_at", None)),
            updated_at=_parse_dt(getattr(s, "updated_at", None)),
            addresses=self._addresses(s),
            metadata=dict(getattr(s, "metadata", None) or {}),
            availability_zone=getattr(s, "availability_zone", None) or "nova",
        )

    # ------------------------------------------------------------------ identity / compute

    def list_projects(self) -> list[Project]:
        return sorted(
            (
                Project(p.id, p.name, getattr(p, "description", "") or "", bool(p.is_enabled))
                for p in self._conn.identity.projects()
            ),
            key=lambda p: p.name,
        )

    def list_servers(self, project_id: str | None = None) -> list[Server]:
        kwargs: dict = {"details": True}
        if self.all_projects:
            kwargs["all_projects"] = True
        if project_id:
            kwargs["project_id"] = project_id
        return sorted(
            (self._map_server(s) for s in self._conn.compute.servers(**kwargs)),
            key=lambda s: (s.project_id, s.name),
        )

    def get_server(self, server_id: str) -> Server:
        server = self._conn.compute.find_server(server_id, ignore_missing=True)
        if server is None:
            raise NotFound("server", server_id)
        return self._map_server(self._conn.compute.get_server(server.id))

    def start_server(self, server_id: str) -> Server:
        server = self.get_server(server_id)
        if server.status is ServerStatus.ACTIVE:
            raise InvalidState(f"server {server.name!r} is already ACTIVE")
        self._conn.compute.start_server(server.id)
        self._conn.compute.wait_for_server(
            self._conn.compute.get_server(server.id), status="ACTIVE"
        )
        return self.get_server(server.id)

    def stop_server(self, server_id: str) -> Server:
        server = self.get_server(server_id)
        if server.status is not ServerStatus.ACTIVE:
            raise InvalidState(f"server {server.name!r} is {server.status.value}, not ACTIVE")
        self._conn.compute.stop_server(server.id)
        self._conn.compute.wait_for_server(
            self._conn.compute.get_server(server.id), status="SHUTOFF"
        )
        return self.get_server(server.id)

    def delete_server(self, server_id: str) -> None:
        server = self.get_server(server_id)
        self._conn.compute.delete_server(server.id, ignore_missing=False)

    def list_flavors(self) -> list[Flavor]:
        return sorted(
            (
                Flavor(f.id, f.name, int(f.vcpus), int(f.ram), int(f.disk))
                for f in self._conn.compute.flavors(details=True)
            ),
            key=lambda f: (f.vcpus, f.ram_mb),
        )

    def list_images(self) -> list[Image]:
        return sorted(
            (
                Image(
                    i.id,
                    i.name,
                    i.status or "active",
                    int(getattr(i, "size", 0) or 0),
                    int(getattr(i, "min_disk", 0) or 0),
                    int(getattr(i, "min_ram", 0) or 0),
                    getattr(i, "visibility", "public") or "public",
                )
                for i in self._conn.image.images()
            ),
            key=lambda i: i.name,
        )

    def get_server_metrics(self, server_id: str) -> ServerMetrics | None:
        """Gnocchi/Ceilometer are not part of every deployment; without telemetry the audit falls
        back to status/age heuristics. Hook a metrics source here when one is available."""
        return None

    # ------------------------------------------------------------------ storage / network

    def list_volumes(self, project_id: str | None = None) -> list[Volume]:
        kwargs: dict = {"details": True}
        if self.all_projects:
            kwargs["all_projects"] = True
        volumes = []
        for v in self._conn.block_storage.volumes(**kwargs):
            owner = getattr(v, "project_id", None) or ""
            if project_id and owner != project_id:
                continue
            volumes.append(
                Volume(
                    id=v.id,
                    name=v.name or v.id,
                    size_gb=int(v.size),
                    status=_volume_status(v.status),
                    project_id=owner,
                    created_at=_parse_dt(getattr(v, "created_at", None)),
                    attached_to=tuple(
                        a.get("server_id") for a in (v.attachments or []) if a.get("server_id")
                    ),
                    volume_type=getattr(v, "volume_type", None) or "",
                    bootable=str(getattr(v, "is_bootable", False)).lower() == "true",
                )
            )
        return sorted(volumes, key=lambda v: (v.project_id, v.name))

    def list_networks(self, project_id: str | None = None) -> list[Network]:
        networks = []
        for n in self._conn.network.networks():
            owner = getattr(n, "project_id", None) or ""
            external = bool(getattr(n, "is_router_external", False))
            if project_id and owner != project_id and not external:
                continue
            networks.append(Network(n.id, n.name, owner, external, tuple(n.subnet_ids or ())))
        return sorted(networks, key=lambda n: n.name)

    def list_floating_ips(self, project_id: str | None = None) -> list[FloatingIP]:
        kwargs = {"project_id": project_id} if project_id else {}
        ports_to_servers: dict[str, str] = {}
        fips = []
        for f in self._conn.network.ips(**kwargs):
            server_id = None
            if f.port_id:
                if f.port_id not in ports_to_servers:
                    port = self._conn.network.get_port(f.port_id)
                    if port and getattr(port, "device_owner", "").startswith("compute:"):
                        ports_to_servers[f.port_id] = port.device_id
                server_id = ports_to_servers.get(f.port_id)
            fips.append(
                FloatingIP(
                    id=f.id,
                    address=f.floating_ip_address,
                    project_id=getattr(f, "project_id", None) or "",
                    created_at=_parse_dt(getattr(f, "created_at", None)),
                    network_id=f.floating_network_id,
                    port_id=f.port_id,
                    server_id=server_id,
                    status=f.status or "DOWN",
                )
            )
        return sorted(fips, key=lambda f: f.address)
