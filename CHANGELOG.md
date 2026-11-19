# Changelog

All notable changes to Nginx Observability are documented here.

## [Unreleased]

### Added

- `install_grafana.py --lang pt-BR|both`: Brazilian Portuguese dashboards and alert texts from one catalog (`deploy/grafana/i18n/pt-BR.json`), so the English dashboards stay the single source. With `both`, each dashboard links to its other-language twin keeping variables and time range; alerts are installed once, in Portuguese by default when Portuguese is chosen.
- `install_grafana.py --carousel`: one pinned Application Detail page per (server, app) with traffic, in a "Carousel" subfolder, and a Grafana playlist that rotates Overview and those pages for a TV / kiosk screen (`--carousel-interval`, `--carousel-apps`). Pages of pairs that stopped reporting are removed on the next run.
- Per-server alert limits on the central server: Prometheus also loads `deploy/central/local-rules/*.yml` (git-ignored; `thresholds-override.yml.example` shows the override records), so a slower application such as a ticketing system gets its own P95 or 5xx limits without changing the repository.
- `tests/verify_grafana_install.py`: offline checks for translation coverage, language links, translated table columns, lab-only rule filtering and carousel pages.

### Fixed

- The installer no longer installs the three lab-only rules (application health endpoint, Nginx health endpoint, nginxlog-exporter) into an existing Grafana, where they sat in "No data"; `--include-lab-rules` keeps them. "Nginx access log parse errors" treats missing data as OK, because Alloy agents create the counter only on the first malformed line, and its texts name the collector instead of the exporter; the Security panel is now "Log parse errors (period)" and shows 0 while traffic is collected without errors.
- `install_grafana.py --dry-run` prints "would create / would update" instead of reading as if the changes had been made.

- Health stats no longer turn missing data into a healthy-looking zero: `or vector(0)` was removed, and zero is shown only while the traffic counter has samples. Exporter parse errors now count the selected period instead of a lifetime total.
- Stat and graph colors follow the alert limits (5xx share 5% / 15%, P95 0.5 s / 1 s); values without an alert limit use a neutral color.
- Error views show the 5xx share in percent, per application, and rank applications by 5xx only; 4xx no longer inflate "errors". Application Detail replaces the always-zero 429 stat with the 5xx share.
- Overview starts with a service and collection health strip (applications, Nginx, exporter, Alloy, Loki) and an active-alerts list; HTTP and availability alert rules link to their Overview panels.
- The Source IP filter (Live Logs, Security and their Explore links) uses a raw LogQL string, so an escaped regex such as `172\.20\.0\.6` no longer fails with "invalid char escape".

### Changed

- Dashboards keep servers apart when Server = All: "Requests by application", "Applications with the most 5xx" (now top 5), the P50/P95/P99 stats, the Security trends and tables show one entry per app and server ("app-a (lab2)"); log tables gain a Server column and drop the duplicate raw `time` column; count bars use plain integers instead of repeated "1 K" ticks; the health strip keeps a minimum tile size instead of shrinking labels.
- Grafana upgraded from 12.4.15 to 13.2.2 (Marco 04 installs into an existing Grafana 13). Dashboards, datasources and alert rules load unchanged; pipeline and alerting suites pass.
- Every Prometheus target and Loki stream carries a `server` label (`lab` in this lab), and all four dashboards have a Server variable applied to every query and Explore link.
- Alert limits are defaults applied to every (server, app) pair with traffic, with optional per-pair overrides; a new application or server gets 5xx and latency alerts without editing the rules. HTTP alerts group by server and app.

- Stat panels use instant queries, so during a collection outage they show "No samples" instead of repeating the last value from before the failure (found by stopping the exporter for two minutes).
- Security's 403/404/5xx rate stats show 0 while traffic is collected but none of those responses occurred, instead of "No samples".
- HTTP 5xx and latency alerts treat missing data as OK: their per-app limits exist only while the exporter reports traffic, and an exporter outage is already signalled by its own alert, so the outage no longer adds four NoData alerts.

- Application Detail's slowest-request table applied `ms` to every column (Status showed `200 ms`); the unit now applies only to the duration column, which is shown before the path.
- Security's scanner-path and repeated-origin panels labelled bars only by application; they are now tables with App / Path / Events and App / Source IP / 4xx-5xx events, sorted by count.
- Live Logs states its real 5 s refresh (Grafana's minimum) instead of 2 s.

- Overview "P95 by application" and "5xx share by application" grouped only by app, merging the same app from different servers; they now group by server and app.
- "Application unavailable" matched app and Nginx health only by `instance`; it now matches by `server` and `instance`.

### Added

- Compose profile `lab2`: a simulated second server (Nginx, three apps, traffic generator and the Marco 04 Alloy agent pushing logs and metrics with `server="lab2"`), off by default. Prometheus accepts remote writes for it.
- Agent configuration for monitored servers (`config/agent/config.alloy`): Alloy alone tails the sanitized JSON logs, pushes them to Loki and derives the HTTP metrics (same names and labels as nginxlog-exporter) for Prometheus remote_write; lab2 runs it.
- Alert "Monitored server agent stopped sending", per server, for agents that push and therefore never report `up == 0`.
- Deployment packages: `deploy/central` (Loki and Prometheus on loopback, host Nginx ingress template with TLS, per-agent credentials and IP allowlist), `deploy/agent` (Alloy container, sanitized log_format, logrotate) and `scripts/install_grafana.py`, which installs datasources (own UIDs), dashboards and alert rules into an existing Grafana through its API. Guide: `docs/implantacao-homologacao.md`.

- GitHub Actions workflow that rebuilds Loki v3.7.10 with Go 1.26.11 and the upstream WAL fix (grafana/loki#25118), using Loki's own Dockerfile; it tests the fix, checks the Go version, scans with Trivy and publishes to GHCR only on a manual run.

### Security

- Loki now runs `ghcr.io/tsathler/loki:3.7.10-go1.26.11-walfix`, pinned by digest: Loki v3.7.10 rebuilt with Go 1.26.11 (fixes CVE-2026-97054) and the upstream WAL replay fix (grafana/loki#25118). The image passed the fix's regression test and a Trivy scan with no findings; the stack passed a graceful restart with marker and fixed-window checks, the isolated persistence regression and the integration suite. The local-only risk acceptance for CVE-2026-97054 is closed.

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
