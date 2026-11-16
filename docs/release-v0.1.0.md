# Release preparation: v0.1.0

**Status:** **NO-GO**; prepared locally, no tag or publication created.

**Reavaliação técnica:** dependências Nginx/Grafana e minimização de logs remediadas e testadas em 2026-11-16, mas a varredura de todas as imagens encontrou candidatos CRITICAL/HIGH adicionais sem adjudicação completa. **Release NO-GO:** titularidade MIT permanece pendente e não foi possível fazer revisão visual de Application Detail e Live Logs nesta sessão. Esta release não está homologada para produção.

**Target:** `v0.1.0`
**Scope:** portfolio/demo release only. This project has not been homologated for production use.

## Release summary

Nginx Observability is a reproducible Docker Compose lab for multi-application Nginx telemetry. It demonstrates per-application HTTP metrics and logs, provisioned Grafana dashboards and alert rules, bounded synthetic traffic, retention and log rotation, plus recovery and integration tests.

The prepared release includes Nginx, Prometheus, Loki, Grafana Alloy, Grafana, the nginxlog-exporter, three demo applications, and a local-only alert receiver. A root MIT license text is present for project-owned source, configuration, dashboard JSON, and documentation, but the rights holder has not confirmed authority to grant those rights; treat distribution as blocked until confirmed. Container components keep their individual upstream licenses; see [license audit](license-audit.md).

## Verification status

The runtime test results recorded in [final audit](final-audit.md) cover integration/scenarios/persistence, reliability, alert transitions and local delivery, loopback/authentication/network checks, and dashboard API queries. Re-run the commands in README before tagging because those results describe the recorded local environment, not every user's machine.

The latest local validation was executed on 2026-11-16:

| Verification | Result |
|---|---|
| `python tests/verify_pipeline.py --verify-scenarios --verify-persistence` | Pass: 3 apps; status/method/latency metrics; 31 PromQL + 7 LogQL; 4 dashboards; bounded scenarios; loopback/auth checks; persistence after service restart. |
| `python tests/verify_pipeline.py --verify-reliability` | Pass: 21 unique Loki events (7 per app), 2 rotations, recovery checks; exporter outage backfill gap reproduced. |
| `python tests/verify_alerting.py` | Pass: health/idle, outage, 5xx, P95, recovery, and local webhook delivery. |
| `python tests/verify_log_privacy.py` | Pass: synthetic secrets absent from active/rotated access logs and Loki. |
| `python tests/audit_repository_history.py` | Pass for known secret/corporate/artifact patterns across reachable history. |
| Compose, dashboard JSON, 11 SPDX files, CVE summary, `git diff --check` | Pass. Git only reported LF-to-CRLF working-copy normalization notices. |
| Browser visual review | Not available: browser access host unavailable and no browser listed; no screenshots claimed. |

The browser visual review for Application Detail and Live Logs was not completed in this session: the Windows browser automation helper could not enumerate windows and no supported browser automation package or Grafana image renderer was available. No screenshots are included. Do not treat API frames as visual confirmation.

## Publication checklist

- [x] Inspect the 31-commit initial local delta and preserve history.
- [x] Add MIT text for repository-owned files and document third-party license boundaries.
- [x] Audit reachable Git history for common credentials and sensitive artifact paths.
- [x] Keep `.env` variants, logs, and Python cache files out of Git; retain `.env.example`.
- [x] Keep published ports on loopback and Grafana authentication enabled.
- [x] Prepare `CHANGELOG.md` and this release note without creating a tag.
- [x] Generate Trivy SBOMs and scan summary for all 11 image artifacts used by Compose; results include untriaged CRITICAL/HIGH candidates and block publication.
- [x] Document that production deployment is not approved or validated.
- [ ] Capture and review the Application Detail and Live Logs dashboards in a real browser; add only genuine screenshots.
- [ ] Confirm the copyright holder named in `LICENSE` before publication.
- [x] Re-run integration, reliability, alerting, privacy, history, Compose, JSON/dashboard, and Git whitespace checks for this audit; the security scanner found outstanding CVEs, so the release remains NO-GO.
- [ ] Review the final staged diff and confirm no local credentials or operational data are included.
- [ ] Obtain maintainer authorization before creating local tag `v0.1.0`.
- [ ] Obtain separate authorization before any push or hosted release publication.

## Risks and release boundaries

- Prometheus historical completeness after the old mmap warning is inconclusive; the current version and restart tests pass, but no independent historical source exists.
- Exporter restarts can leave metric-counter gaps even while corresponding requests remain searchable in Loki.
- Loki disk-free capacity is not measured in this configuration.
- Prometheus and Loki have no native auth in the demo; loopback-only publication is part of the lab boundary.
- Image tags are pinned by version, not digest. SBOMs now exist for scanned image digests, but tags can resolve to different bytes later; package-level license/legal review is still incomplete.
- Trivy 0.76.2 identified CRITICAL/HIGH package findings in the exporter, Loki, Alloy, and locally built Python images, plus HIGH findings in Nginx, Prometheus, and Grafana. The scan did not determine reachability or adjudicate false positives. See [`pre-release-audit.md`](pre-release-audit.md) and [`sbom/`](sbom/).
- The MIT copyright attribution comes from the current Git author identity and has not been independently confirmed by the rights holder.
- Do not market this Compose configuration as production-ready, secure for shared hosting, or homologated for corporate operation.

## Security remediation record — 2026-11-16

- Updated pinned images to `nginx:1.30.6-alpine` and `grafana/grafana:12.4.15`; startup/migration and integration, security, alert, persistence, and reliability suites passed. See [pre-release audit](pre-release-audit.md) for advisory references and evidence. No complete image CVE/SBOM scan was run.
- Nginx now logs only allowlisted route names (unknown paths collapse to `/_unclassified`), method, app, status, duration, response bytes, and source IP. Raw request targets/query strings, Cookie, Authorization, Referer, and User-Agent are not persisted in new access events. `python tests/verify_log_privacy.py` passed with synthetic canaries.
- Historical events and rotated files were not purged; old fields can remain in local volumes until retention/rotation. No real traffic was used during the test. Do not treat the privacy check as a historical scrub.
- Full scan results and remaining limits—including untriaged CVEs, exporter outage counter gaps, no full restore rehearsal, no reliable free-space metric, pending visual review, and unconfirmed copyright—are documented in `pre-release-audit.md`, `security-audit.md`, and `sbom/`.

### Updated publication checklist

- [x] Update Nginx and Grafana from the previously flagged versions and validate the lab.
- [x] Verify new access events do not persist synthetic path/query/header canaries.
- [x] Re-run integration/scenario/persistence, reliability, alerting, and Compose validation.
- [ ] Confirm the actual rights holder for the MIT attribution.
- [ ] Complete visual review of Application Detail and Live Logs, or leave clearly marked as pending.
- [ ] Review staged release contents; create a tag only after separate authorization.
