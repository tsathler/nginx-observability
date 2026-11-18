# Changelog

All notable changes to Nginx Observability are documented here.

## [Unreleased]

### Fixed

- Health stats no longer turn missing data into a healthy-looking zero: `or vector(0)` was removed, and zero is shown only while the traffic counter has samples. Exporter parse errors now count the selected period instead of a lifetime total.
- Stat and graph colors follow the alert limits (5xx share 5% / 15%, P95 0.5 s / 1 s); values without an alert limit use a neutral color.
- Error views show the 5xx share in percent, per application, and rank applications by 5xx only; 4xx no longer inflate "errors". Application Detail replaces the always-zero 429 stat with the 5xx share.
- Overview starts with a service and collection health strip (applications, Nginx, exporter, Alloy, Loki) and an active-alerts list; HTTP and availability alert rules link to their Overview panels.
- The Source IP filter (Live Logs, Security and their Explore links) uses a raw LogQL string, so an escaped regex such as `172\.20\.0\.6` no longer fails with "invalid char escape".

### Changed

- Every Prometheus target and Loki stream carries a `server` label (`lab` in this lab), and all four dashboards have a Server variable applied to every query and Explore link.
- Alert limits are defaults applied to every (server, app) pair with traffic, with optional per-pair overrides; a new application or server gets 5xx and latency alerts without editing the rules. HTTP alerts group by server and app.

### Added

- GitHub Actions workflow that rebuilds Loki v3.7.10 with Go 1.26.11 and the upstream WAL fix (grafana/loki#25118), using Loki's own Dockerfile; it tests the fix, checks the Go version, scans with Trivy and publishes to GHCR only on a manual run. Not yet run; Compose still uses the official image.

### Removed

- `scripts/build_dashboards.py`: it had diverged from the provisioned dashboards. The JSON files under `config/grafana/dashboards/` are the source of truth.

## [0.1.0] - 2026-11-17

### Added

- Docker Compose lab with Nginx and three independently identified demo applications.
- Per-application HTTP metrics, structured logs, and Prometheus/Loki/Grafana provisioning.
- Overview, Application Detail, Live Logs, and Security Grafana dashboards.
- Bounded synthetic scenarios for normal traffic, degradation, scanning patterns, traffic peaks, and latency.
- Configurable retention, access-log rotation, recovery checks, and operational alert rules.
- Local alert webhook receiver and automated integration, reliability, alerting, and repository-history checks.
- Root MIT license for project-authored files; the rights holder was confirmed by the maintainer on 2026-11-17. Third-party components retain their own licenses.

### Validated

- Multi-application separation, HTTP status/method coverage, histogram percentiles, LogQL/PromQL queries, and Grafana provisioning.
- Persistence across service restarts, two log-rotation cycles, recovery after component outages, and local alert delivery.
- Prometheus 3.16.0 startup/recovery after an earlier mmap chunk warning on 3.8.1.

### Known limitations

- Loki `3.7.10` is built with Go `1.26.10` (CVE-2026-97054, possible process panic). Risk accepted by the maintainer for the local lab only; Loki must not accept connections from other machines until an image built with Go `1.26.11`+ is adopted. See `docs/cve-triage.md`.
- Remaining HIGH package findings (Debian base of the Python images, Grafana, Prometheus) have no CRITICAL counterpart and are triaged with their preconditions in `docs/cve-triage.md`; SBOMs are under `docs/sbom/`.
- Off-host backup is not scheduled; it is a Marco 04 requirement.
- Cosmetic dashboard items: path bars are not reordered by value, recent-request tables show the raw `time` field, some stat titles truncate on narrow screens.
- The exporter does not backfill Prometheus counters for requests made while it is unavailable.
- Loki filesystem storage has no reliable free-space metric or byte quota in this lab.
- Historical completeness of the Prometheus TSDB volume is not independently proven.
- This is a local demonstration, not a production-homologated deployment.
