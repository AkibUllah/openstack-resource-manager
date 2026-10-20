"""`osrm` command line interface."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console

from . import __version__
from .audit import run_audit
from .config import Config, build_client, load_config
from .exceptions import OsrmError
from .export import FORMATS, dump, render
from .models import to_row
from .pricing import ZERO, PriceTable, estimate_costs, money

app = typer.Typer(
    help="Inventory, audit and cost-estimate OpenStack resources.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
servers_app = typer.Typer(help="List, inspect and control servers.", no_args_is_help=True)
volumes_app = typer.Typer(help="Block volumes.", no_args_is_help=True)
ips_app = typer.Typer(help="Floating IPs.", no_args_is_help=True)
cost_app = typer.Typer(help="Cost estimation.", no_args_is_help=True)
app.add_typer(servers_app, name="servers")
app.add_typer(volumes_app, name="volumes")
app.add_typer(ips_app, name="ips")
app.add_typer(cost_app, name="cost")

console = Console()
err_console = Console(stderr=True)


class State:
    config: Config
    client = None
    fmt: str = "table"
    project: str | None = None

    @classmethod
    def get_client(cls):
        if cls.client is None:
            cls.client = _run(build_client, cls.config)
        return cls.client


def _fmt_option():
    return typer.Option("table", "--format", "-f", help="Output format: table, json or csv.")


def _check_format(fmt: str) -> str:
    if fmt not in FORMATS:
        raise typer.BadParameter(f"must be one of {', '.join(FORMATS)}")
    return fmt


def _resolve_project(client, project: str | None) -> str | None:
    """Accept a project id or name; return the id."""
    if project is None:
        return None
    for p in client.list_projects():
        if project in (p.id, p.name):
            return p.id
    raise typer.BadParameter(f"project {project!r} not found", param_hint="--project")


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"osrm {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    backend: str | None = typer.Option(
        None, "--backend", help="fake or openstack (overrides config/env)."
    ),
    cloud: str | None = typer.Option(
        None, "--cloud", help="clouds.yaml entry (overrides OS_CLOUD)."
    ),
    config_file: Path | None = typer.Option(
        None, "--config", help="Path to osrm.toml (default ~/.osrm.toml)."
    ),
    version: bool = typer.Option(False, "--version", callback=_version_callback, is_eager=True),
) -> None:
    config = load_config(path=config_file)
    if backend:
        config = Config(
            backend=backend,
            cloud=config.cloud,
            region=config.region,
            pricing=config.pricing,
            audit=config.audit,
            source=config.source,
        )
    if cloud:
        config = Config(
            backend=config.backend,
            cloud=cloud,
            region=config.region,
            pricing=config.pricing,
            audit=config.audit,
            source=config.source,
        )
    State.config = config
    State.client = None


def _run(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except OsrmError as exc:
        err_console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc


# ------------------------------------------------------------------------------- servers

SERVER_COLUMNS = ["id", "name", "status", "flavor", "project", "ip", "age_days"]


def _server_rows(client, servers) -> list[dict]:
    flavors = {f.id: f.name for f in client.list_flavors()}
    projects = {p.id: p.name for p in client.list_projects()}
    now = getattr(client, "now", None)
    from .models import utcnow

    now = now or utcnow()
    rows = []
    for s in servers:
        row = to_row(s)
        row.update(
            flavor=flavors.get(s.flavor_id, s.flavor_id),
            project=projects.get(s.project_id, s.project_id),
            ip=", ".join(ip for ips in s.addresses.values() for ip in ips),
            age_days=int(s.age_days(now)),
        )
        rows.append(row)
    return rows


@servers_app.command("list")
def servers_list(
    project: str | None = typer.Option(None, "--project", "-p", help="Project id or name."),
    status: str | None = typer.Option(None, "--status", help="Filter by status, e.g. SHUTOFF."),
    fmt: str = _fmt_option(),
) -> None:
    """List servers across projects."""
    fmt = _check_format(fmt)
    client = State.get_client()
    servers = _run(client.list_servers, _resolve_project(client, project))
    if status:
        servers = [s for s in servers if s.status.value == status.upper()]
    rows = _server_rows(client, servers)
    render(
        rows,
        fmt,
        console,
        title=f"Servers ({len(rows)})",
        columns=SERVER_COLUMNS if fmt == "table" else None,
    )


@servers_app.command("show")
def servers_show(
    server: str = typer.Argument(..., help="Server id or name."), fmt: str = _fmt_option()
) -> None:
    """Show one server with its flavor, volumes, floating IPs and metrics."""
    fmt = _check_format(fmt)
    client = State.get_client()
    s = _run(client.get_server, server)
    flavor = next((f for f in client.list_flavors() if f.id == s.flavor_id), None)
    volumes = [v for v in client.list_volumes(s.project_id) if s.id in v.attached_to]
    fips = [f for f in client.list_floating_ips(s.project_id) if f.server_id == s.id]
    metrics = client.get_server_metrics(s.id)
    detail = to_row(s)
    detail.update(
        flavor=to_row(flavor) if flavor else None,
        volumes=[{"id": v.id, "name": v.name, "size_gb": v.size_gb} for v in volumes],
        floating_ips=[f.address for f in fips],
        metrics=to_row(metrics) if metrics else None,
    )
    if fmt == "json":
        console.print_json(json.dumps(detail, indent=2, default=str))
        return
    rows = [{"field": k, "value": v} for k, v in detail.items()]
    render(rows, fmt, console, title=f"Server {s.name}", columns=["field", "value"])


PAST_TENSE = {"stop": "stopped", "start": "started", "delete": "deleted"}


def _mutate(action: str, server: str, dry_run: bool, yes: bool = True) -> None:
    client = State.get_client()
    target = _run(client.get_server, server)
    if dry_run:
        console.print(
            f"[yellow]dry-run:[/yellow] would {action} server {target.name} "
            f"({target.id}, {target.status.value})"
        )
        return
    if not yes:
        confirmed = typer.confirm(f"{action.capitalize()} server {target.name} ({target.id})?")
        if not confirmed:
            console.print("aborted")
            raise typer.Exit(code=1)
    method = getattr(client, f"{action}_server")
    result = _run(method, target.id)
    if result is None:
        console.print(f"[green]deleted[/green] server {target.name} ({target.id})")
    else:
        console.print(
            f"[green]{PAST_TENSE[action]}[/green] server {result.name} ({result.id}) "
            f"-> {result.status.value}"
        )


@servers_app.command("stop")
def servers_stop(
    server: str, dry_run: bool = typer.Option(False, "--dry-run", help="Show what would happen.")
) -> None:
    """Stop (power off) a server."""
    _mutate("stop", server, dry_run)


@servers_app.command("start")
def servers_start(server: str, dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    """Start a stopped server."""
    _mutate("start", server, dry_run)


@servers_app.command("delete")
def servers_delete(
    server: str,
    dry_run: bool = typer.Option(False, "--dry-run"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Delete a server (volumes are detached, floating IPs released)."""
    _mutate("delete", server, dry_run, yes=yes)


# ------------------------------------------------------------------------------- volumes / ips

VOLUME_COLUMNS = ["id", "name", "size_gb", "status", "attached_to", "project", "age_days"]
IP_COLUMNS = ["id", "address", "status", "server_id", "project", "age_days"]


def _with_project_and_age(client, items) -> list[dict]:
    projects = {p.id: p.name for p in client.list_projects()}
    from .models import utcnow

    now = getattr(client, "now", None) or utcnow()
    rows = []
    for item in items:
        row = to_row(item)
        row["project"] = projects.get(item.project_id, item.project_id)
        row["age_days"] = int((now - item.created_at).total_seconds() // 86400)
        rows.append(row)
    return rows


@volumes_app.command("list")
def volumes_list(
    project: str | None = typer.Option(None, "--project", "-p"),
    orphaned: bool = typer.Option(False, "--orphaned", help="Only available, unattached volumes."),
    fmt: str = _fmt_option(),
) -> None:
    """List block volumes."""
    fmt = _check_format(fmt)
    client = State.get_client()
    volumes = _run(client.list_volumes, _resolve_project(client, project))
    if orphaned:
        volumes = [v for v in volumes if v.is_orphaned]
    rows = _with_project_and_age(client, volumes)
    title = f"{'Orphaned volumes' if orphaned else 'Volumes'} ({len(rows)})"
    render(rows, fmt, console, title=title, columns=VOLUME_COLUMNS if fmt == "table" else None)


@ips_app.command("list")
def ips_list(
    project: str | None = typer.Option(None, "--project", "-p"),
    unused: bool = typer.Option(False, "--unused", help="Only IPs not attached to any port."),
    fmt: str = _fmt_option(),
) -> None:
    """List floating IPs."""
    fmt = _check_format(fmt)
    client = State.get_client()
    fips = _run(client.list_floating_ips, _resolve_project(client, project))
    if unused:
        fips = [f for f in fips if f.is_unused]
    rows = _with_project_and_age(client, fips)
    title = f"{'Unused floating IPs' if unused else 'Floating IPs'} ({len(rows)})"
    render(rows, fmt, console, title=title, columns=IP_COLUMNS if fmt == "table" else None)


# ------------------------------------------------------------------------- projects / audit / cost


@app.command("projects")
def projects(fmt: str = _fmt_option()) -> None:
    """List projects (tenants) visible to the configured credentials."""
    fmt = _check_format(fmt)
    client = State.get_client()
    rows = [to_row(p) for p in _run(client.list_projects)]
    render(rows, fmt, console, title=f"Projects ({len(rows)})")


@app.command("audit")
def audit(
    project: str | None = typer.Option(None, "--project", "-p"),
    kind: list[str] | None = typer.Option(
        None, "--kind", "-k", help="Only these finding kinds (repeatable)."
    ),
    min_severity: str | None = typer.Option(None, "--min-severity", help="low, medium or high."),
    fmt: str = _fmt_option(),
) -> None:
    """Find idle, oversized, orphaned and broken resources with the money they cost."""
    fmt = _check_format(fmt)
    client = State.get_client()
    table = PriceTable.load(State.config.pricing)
    report = _run(run_audit, client, table, State.config.audit, _resolve_project(client, project))
    findings = report.filter(set(kind) if kind else None, min_severity)
    rows = [f.to_row() for f in findings]
    if fmt == "table":
        render(
            rows,
            fmt,
            console,
            title=f"Audit findings ({len(rows)})",
            columns=[
                "severity",
                "kind",
                "name",
                "project_id",
                "message",
                "monthly_saving",
                "recommendation",
            ],
        )
        scanned = ", ".join(f"{v} {k}" for k, v in report.scanned.items())
        total = money(sum((f.monthly_saving for f in findings), ZERO))
        console.print(
            f"scanned {scanned} · potential saving [bold]{total} {report.currency}/month[/bold]"
        )
    elif fmt == "json":
        payload = {
            "scanned": report.scanned,
            "currency": report.currency,
            "total_monthly_saving": str(money(sum((f.monthly_saving for f in findings), ZERO))),
            "findings": rows,
        }
        console.print_json(dump([payload], "json")[1:-1].strip())
    else:
        render(rows, fmt, console)


@cost_app.command("estimate")
def cost_estimate(
    project: str | None = typer.Option(None, "--project", "-p", help="Project id or name."),
    pricing: Path | None = typer.Option(None, "--pricing", help="Custom pricing YAML."),
    detail: bool = typer.Option(False, "--detail", help="Show every resource, not just totals."),
    fmt: str = _fmt_option(),
) -> None:
    """Estimate hourly/monthly cost from the flavor and storage price table."""
    fmt = _check_format(fmt)
    client = State.get_client()
    table = PriceTable.load(pricing or State.config.pricing)
    estimate = _run(estimate_costs, client, table, _resolve_project(client, project))
    projects_by_id = {p.id: p.name for p in client.list_projects()}

    summary_rows = [
        {
            "project": projects_by_id.get(pid, pid),
            "monthly": str(money(total)),
            "currency": estimate.currency,
        }
        for pid, total in estimate.by_project().items()
    ]
    type_rows = [
        {"resource_type": rtype, "monthly": str(money(total)), "currency": estimate.currency}
        for rtype, total in estimate.by_type().items()
    ]
    if fmt == "json":
        payload = {
            "currency": estimate.currency,
            "hours_per_month": estimate.hours_per_month,
            "hourly_total": str(money(estimate.hourly_total)),
            "monthly_total": str(money(estimate.monthly_total)),
            "by_project": {
                projects_by_id.get(k, k): str(money(v)) for k, v in estimate.by_project().items()
            },
            "by_type": {k: str(money(v)) for k, v in estimate.by_type().items()},
            "unpriced_flavors": sorted({ln.detail.split(" · ")[0] for ln in estimate.unpriced}),
            "lines": [ln.to_row(estimate.hours_per_month) for ln in estimate.lines]
            if detail
            else [],
        }
        console.print_json(dump([payload], "json")[1:-1].strip())
        return
    if fmt == "csv":
        render([ln.to_row(estimate.hours_per_month) for ln in estimate.lines], fmt, console)
        return
    render(summary_rows, fmt, console, title="Monthly cost by project")
    render(type_rows, fmt, console, title="Monthly cost by resource type")
    if detail:
        render(
            [ln.to_row(estimate.hours_per_month) for ln in estimate.lines],
            fmt,
            console,
            title="Resources",
            columns=[
                "resource_type",
                "name",
                "project_id",
                "detail",
                "hourly",
                "monthly",
                "exact_price",
            ],
        )
    console.print(
        f"total [bold]{money(estimate.monthly_total)} {estimate.currency}/month[/bold] "
        f"({money(estimate.hourly_total)} {estimate.currency}/hour, "
        f"{estimate.hours_per_month} h/month, prices: {table.source})"
    )
    if estimate.unpriced:
        names = sorted({ln.detail.split(" · ")[0] for ln in estimate.unpriced})
        console.print(
            f"[yellow]note:[/yellow] no exact price for flavors {names}; used per-vCPU/RAM fallback"
        )


# ------------------------------------------------------------------------------- export


@app.command("export")
def export(
    resource: str = typer.Option(
        "all", "--resource", "-r", help="servers, volumes, ips, flavors, images, projects or all."
    ),
    project: str | None = typer.Option(None, "--project", "-p"),
    fmt: str = typer.Option("json", "--format", "-f", help="json, csv or table."),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Write to a file instead of stdout."
    ),
) -> None:
    """Export inventory as JSON, CSV or a text table."""
    fmt = _check_format(fmt)
    client = State.get_client()
    pid = _resolve_project(client, project)
    collections = {
        "servers": lambda: [to_row(s) for s in client.list_servers(pid)],
        "volumes": lambda: [to_row(v) for v in client.list_volumes(pid)],
        "ips": lambda: [to_row(f) for f in client.list_floating_ips(pid)],
        "flavors": lambda: [to_row(f) for f in client.list_flavors()],
        "images": lambda: [to_row(i) for i in client.list_images()],
        "projects": lambda: [to_row(p) for p in client.list_projects()],
    }
    if resource != "all" and resource not in collections:
        raise typer.BadParameter(f"unknown resource {resource!r}", param_hint="--resource")
    selected = list(collections) if resource == "all" else [resource]

    if fmt == "json" and resource == "all":
        text = dump([{name: collections[name]() for name in selected}], "json")[1:-1].strip()
    else:
        chunks = []
        for name in selected:
            rows = _run(collections[name])
            if fmt == "csv" and resource == "all":
                chunks.append(f"# {name}\n{dump(rows, 'csv')}")
            elif fmt == "table":
                chunks.append(dump(rows, "table"))
            else:
                chunks.append(dump(rows, fmt))
        text = "\n".join(chunks)

    if output:
        output.write_text(text, encoding="utf-8")
        console.print(f"wrote {output} ({len(text.splitlines())} lines)")
    else:
        sys.stdout.write(text + ("\n" if not text.endswith("\n") else ""))


if __name__ == "__main__":  # pragma: no cover
    app()
