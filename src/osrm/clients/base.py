"""The CloudClient protocol every backend implements."""

from __future__ import annotations

from typing import Protocol

from ..models import Flavor, FloatingIP, Image, Network, Project, Server, ServerMetrics, Volume


class CloudClient(Protocol):
    name: str

    # ---- identity / compute
    def list_projects(self) -> list[Project]: ...

    def list_servers(self, project_id: str | None = None) -> list[Server]: ...

    def get_server(self, server_id: str) -> Server: ...

    def start_server(self, server_id: str) -> Server: ...

    def stop_server(self, server_id: str) -> Server: ...

    def delete_server(self, server_id: str) -> None: ...

    def list_flavors(self) -> list[Flavor]: ...

    def list_images(self) -> list[Image]: ...

    def get_server_metrics(self, server_id: str) -> ServerMetrics | None:
        """Utilisation averages, or None when the cloud has no telemetry for the server."""

    # ---- storage / network
    def list_volumes(self, project_id: str | None = None) -> list[Volume]: ...

    def list_networks(self, project_id: str | None = None) -> list[Network]: ...

    def list_floating_ips(self, project_id: str | None = None) -> list[FloatingIP]: ...
