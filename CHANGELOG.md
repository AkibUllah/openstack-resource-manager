# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- CodeQL analysis for Python and GitHub Actions on pushes and pull requests to `main` and on a weekly schedule.
- Dependabot version updates for pip, Docker and GitHub Actions, with minor and patch updates grouped per ecosystem.
- README screenshots: `osrm audit` and a servers/cost run on the fake backend.
- Roadmap items tracked as GitHub issues under the v0.2.0 milestone.

### Changed

- CI workflow runs with a read-only `GITHUB_TOKEN`.
- Fake cloud fixtures use neutral project names (`rideshare-prod`, `grocer-staging`, `cashwallet-sandbox`); README sample output regenerated.

## [0.1.0] - 2026-10-25

First public release of OpenStack Resource Manager (osrm).

### Added

- `CloudClient` protocol with two implementations: `OpenStackClient` (openstacksdk, imported lazily, optional extra) and `FakeCloudClient` (three realistic projects: ride-hailing prod, grocery staging, payment sandbox)
- `osrm servers list|show|stop|start|delete` with `--dry-run` and confirmation on delete; lookup by id or name
- `osrm volumes list --orphaned`, `osrm ips list --unused`, `osrm projects`
- `osrm audit`: idle servers (SHUTOFF for N days, or ACTIVE under a CPU threshold), oversized servers, orphaned volumes, unused floating IPs, resources stuck in ERROR, each with severity, a recommendation and the monthly saving in your currency
- `osrm cost estimate [--project X]`: hourly / monthly totals by project and resource type from a YAML flavor price table, with a per-vCPU/RAM fallback for unknown flavors and a note listing them
- `osrm export --format json|csv|table [--output file]` for servers, volumes, IPs, flavors, images, projects or everything
- Configuration layering: defaults < `~/.osrm.toml` < `OSRM_*` / `OS_CLOUD` environment < CLI flags; clouds.yaml is reused unchanged
- Decimal money, timezone-aware timestamps, typed exceptions mapped to exit codes

[Unreleased]: https://github.com/AkibUllah/openstack-resource-manager/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/AkibUllah/openstack-resource-manager/releases/tag/v0.1.0
