# Changelog

All notable changes to Nginx Observability are documented here.

## [0.1.0] - Prepared locally, not tagged (NO-GO)

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

- Trivy 0.76.2 found unresolved CRITICAL/HIGH image-package findings across the exporter, Loki, Alloy, and locally built Python images; some HIGH findings also appear in Nginx, Prometheus, and Grafana. See `docs/pre-release-audit.md` and the SPDX SBOMs under `docs/sbom/`.
- Application Detail and Live Logs still need a visual browser review; no screenshots are included in this prepared release.
- The exporter does not backfill Prometheus counters for requests made while it is unavailable.
- Loki filesystem storage has no reliable free-space metric or byte quota in this lab.
- Historical completeness of the Prometheus TSDB volume is not independently proven.
- This is a local demonstration, not a production-homologated deployment.
