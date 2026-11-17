# Changelog

All notable changes to Nginx Observability are documented here.

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
