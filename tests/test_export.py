from __future__ import annotations

import csv
import io
import json

from osrm.export import dump, to_csv, to_json, to_table
from osrm.models import to_row


def test_to_row_flattens_enums_dates_and_tuples(client):
    row = to_row(client.get_server("srv-01"))
    assert row["status"] == "ACTIVE"
    assert row["created_at"].endswith("+00:00")
    vol = to_row(next(v for v in client.list_volumes() if v.id == "vol-03"))
    assert vol["attached_to"] == ["srv-03"] and vol["status"] == "in-use"


def test_json_and_csv_roundtrip(client):
    rows = [to_row(v) for v in client.list_volumes("p-cashwallet-sandbox")]
    parsed = json.loads(to_json(rows))
    assert [r["id"] for r in parsed] == ["vol-10", "vol-09", "vol-11"]

    reader = list(csv.DictReader(io.StringIO(to_csv(rows))))
    assert len(reader) == 3
    assert reader[1]["attached_to"] == "srv-10"
    assert to_csv([]) == ""


def test_table_and_dump(client):
    rows = [to_row(f) for f in client.list_flavors()]
    table = to_table(rows, title="Flavors", columns=["name", "vcpus", "ram_mb"])
    assert [c.header for c in table.columns] == ["name", "vcpus", "ram_mb"]
    text = dump(rows, "table", columns=["name", "vcpus"])
    assert "c2.highcpu" in text and "16" in text
    assert dump(rows, "json").startswith("[")
