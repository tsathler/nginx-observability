# Release preparation: v0.1.0

**Status:** prepared locally; no tag or publication created.

**Target:** `v0.1.0`
**Scope:** portfolio/demo release only. This project has not been homologated for production use.

## Release summary

Nginx Observability is a reproducible Docker Compose lab for multi-application Nginx telemetry. It demonstrates per-application HTTP metrics and logs, provisioned Grafana dashboards and alert rules, bounded synthetic traffic, retention and log rotation, plus recovery and integration tests.

The prepared release includes Nginx, Prometheus, Loki, Grafana Alloy, Grafana, the nginxlog-exporter, three demo applications, and a local-only alert receiver. The project-owned source, configuration, dashboard JSON, and documentation are licensed under MIT. Container components keep their individual upstream licenses; see [license audit](license-audit.md).

## Verification status

The runtime test results recorded in [final audit](final-audit.md) cover integration/scenarios/persistence, reliability, alert transitions and local delivery, loopback/authentication/network checks, and dashboard API queries. Re-run the commands in README before tagging because those results describe the recorded local environment, not every user's machine.

The browser visual review for Application Detail and Live Logs was not completed in this session: the Windows browser automation helper could not enumerate windows and no supported browser automation package or Grafana image renderer was available. No screenshots are included. Do not treat API frames as visual confirmation.

## Publication checklist

- [x] Inspect the 31-commit initial local delta and preserve history.
- [x] Add MIT text for repository-owned files and document third-party license boundaries.
- [x] Audit reachable Git history for common credentials and sensitive artifact paths.
- [x] Keep `.env` variants, logs, and Python cache files out of Git; retain `.env.example`.
- [x] Keep published ports on loopback and Grafana authentication enabled.
- [x] Prepare `CHANGELOG.md` and this release note without creating a tag.
- [x] Document that production deployment is not approved or validated.
- [ ] Capture and review the Application Detail and Live Logs dashboards in a real browser; add only genuine screenshots.
- [ ] Confirm the copyright holder named in `LICENSE` before publication.
- [ ] Re-run integration, reliability, alerting, security, Compose, and Git whitespace checks immediately before release.
- [ ] Review the final staged diff and confirm no local credentials or operational data are included.
- [ ] Obtain maintainer authorization before creating local tag `v0.1.0`.
- [ ] Obtain separate authorization before any push or hosted release publication.

## Risks and release boundaries

- Prometheus historical completeness after the old mmap warning is inconclusive; the current version and restart tests pass, but no independent historical source exists.
- Exporter restarts can leave metric-counter gaps even while corresponding requests remain searchable in Loki.
- Loki disk-free capacity is not measured in this configuration.
- Prometheus and Loki have no native auth in the demo; loopback-only publication is part of the lab boundary.
- Image tags are pinned by version, not digest, and full package-level SBOM/license inventory for image contents was not produced.
- The MIT copyright attribution comes from the current Git author identity and has not been independently confirmed by the rights holder.
- Do not market this Compose configuration as production-ready, secure for shared hosting, or homologated for corporate operation.
