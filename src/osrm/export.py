"""Render rows as a Rich table, JSON or CSV."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterable

from rich.console import Console
from rich.table import Table

FORMATS = ("table", "json", "csv")


def to_json(rows: list[dict]) -> str:
    return json.dumps(rows, indent=2, default=str)


def to_csv(rows: list[dict], columns: Iterable[str] | None = None) -> str:
    if not rows:
        return ""
    columns = list(columns or rows[0].keys())
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: _flat(row.get(k)) for k in columns})
    return buf.getvalue()


def _flat(value):
    if isinstance(value, (list, tuple)):
        return ";".join(str(v) for v in value)
    if isinstance(value, dict):
        return ";".join(f"{k}={_flat(v)}" for k, v in value.items())
    return value


def to_table(
    rows: list[dict], title: str | None = None, columns: Iterable[str] | None = None
) -> Table:
    columns = list(columns or (rows[0].keys() if rows else []))
    table = Table(title=title, show_lines=False, header_style="bold")
    for col in columns:
        justify = (
            "right"
            if col
            in {
                "hourly",
                "daily",
                "monthly",
                "monthly_saving",
                "size_gb",
                "vcpus",
                "ram_mb",
                "disk_gb",
            }
            else "left"
        )
        table.add_column(col, justify=justify, overflow="fold")
    for row in rows:
        table.add_row(*(str(_flat(row.get(col, ""))) for col in columns))
    return table


def render(
    rows: list[dict], fmt: str, console: Console, title: str | None = None, columns=None
) -> None:
    if fmt == "json":
        console.print_json(to_json(rows))
    elif fmt == "csv":
        console.file.write(to_csv(rows, columns))
    elif fmt == "table":
        if not rows:
            console.print(f"[dim]{title or 'No results'}: nothing to show[/dim]")
            return
        console.print(to_table(rows, title=title, columns=columns))
    else:
        raise ValueError(f"unknown format {fmt!r}; expected one of {FORMATS}")


def dump(rows: list[dict], fmt: str, columns=None) -> str:
    """Plain-string export (used by `osrm export --output`)."""
    if fmt == "json":
        return to_json(rows)
    if fmt == "csv":
        return to_csv(rows, columns)
    if fmt == "table":
        console = Console(record=True, width=160, file=io.StringIO())
        console.print(to_table(rows, columns=columns))
        return console.export_text()
    raise ValueError(f"unknown format {fmt!r}; expected one of {FORMATS}")
