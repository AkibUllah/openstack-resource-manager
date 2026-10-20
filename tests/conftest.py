from __future__ import annotations

import pytest
from typer.testing import CliRunner

from osrm import cli
from osrm.clients.fake import NOW, FakeCloudClient
from osrm.pricing import PriceTable


@pytest.fixture
def client() -> FakeCloudClient:
    return FakeCloudClient()


@pytest.fixture
def table() -> PriceTable:
    return PriceTable.load()


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def env(tmp_path) -> dict[str, str]:
    """Environment for CLI runs: fake backend, no user config file, wide terminal."""
    return {
        "OSRM_BACKEND": "fake",
        "OSRM_CONFIG": str(tmp_path / "missing.toml"),
        "COLUMNS": "200",
        "TERM": "dumb",
        "NO_COLOR": "1",
    }


@pytest.fixture
def shared_client(monkeypatch) -> FakeCloudClient:
    """Make every CLI invocation in a test talk to the same fake cloud (state persists)."""
    fake = FakeCloudClient()
    monkeypatch.setattr(cli, "build_client", lambda config, now=None: fake)
    return fake


def invoke(runner: CliRunner, env: dict, *args: str, input: str | None = None):
    result = runner.invoke(cli.app, list(args), env=env, input=input)
    return result
