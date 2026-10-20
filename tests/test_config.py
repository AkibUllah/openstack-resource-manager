from __future__ import annotations

from pathlib import Path

from osrm.clients.fake import FakeCloudClient
from osrm.config import Config, build_client, load_config


def test_defaults_when_nothing_configured(tmp_path):
    config = load_config(path=tmp_path / "none.toml", env={})
    assert config == Config()
    assert config.backend == "fake" and config.audit.idle_days == 14


def test_toml_file_is_read(tmp_path):
    path = tmp_path / "osrm.toml"
    path.write_text(
        'backend = "openstack"\ncloud = "dhaka-prod"\npricing = "~/prices.yaml"\n\n'
        "[audit]\nidle_days = 30\noversized_min_vcpus = 8\nunknown_key = 1\n"
    )
    config = load_config(path=path, env={})
    assert config.backend == "openstack" and config.cloud == "dhaka-prod"
    assert config.pricing == Path("~/prices.yaml").expanduser()
    assert config.audit.idle_days == 30 and config.audit.oversized_min_vcpus == 8
    assert config.audit.idle_cpu_percent == 5.0  # untouched default
    assert config.source == str(path)


def test_environment_overrides_file(tmp_path):
    path = tmp_path / "osrm.toml"
    path.write_text('backend = "openstack"\ncloud = "a"\n[audit]\nidle_days = 30\n')
    env = {
        "OSRM_BACKEND": "fake",
        "OS_CLOUD": "b",
        "OSRM_IDLE_DAYS": "7",
        "OSRM_IDLE_CPU_PERCENT": "2.5",
    }
    config = load_config(path=path, env=env)
    assert config.backend == "fake" and config.cloud == "b"
    assert config.audit.idle_days == 7 and config.audit.idle_cpu_percent == 2.5


def test_osrm_config_env_points_to_file(tmp_path):
    path = tmp_path / "elsewhere.toml"
    path.write_text('backend = "fake"\nregion = "ctg-1"\n')
    config = load_config(env={"OSRM_CONFIG": str(path)})
    assert config.region == "ctg-1"
    # An explicit path (the CLI --config flag) wins over the environment variable.
    explicit = tmp_path / "explicit.toml"
    explicit.write_text('region = "dhaka-1"\n')
    assert load_config(path=explicit, env={"OSRM_CONFIG": str(path)}).region == "dhaka-1"


def test_build_client_fake_and_unknown():
    assert isinstance(build_client(Config(backend="fake")), FakeCloudClient)
    try:
        build_client(Config(backend="aws"))
    except ValueError as exc:
        assert "unknown backend" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")
