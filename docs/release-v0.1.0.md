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

## Final gate reassessment — 2026-11-17

**Decision: NO-GO.** This is a laboratory/portfolio release and has not been homologated for production.

- The full Prometheus/Loki/Grafana restore drill now passes with archives copied from stopped, consistent service volumes and restored into a disposable isolated Compose project. It verified historical Prometheus series, Loki application streams, Grafana authentication, four dashboards, and both datasources. Original volume names and identities were preserved. The drill does not provide a scheduled or off-host backup policy; backups created for the test are temporary and are deleted after verification.
- Trivy's `UNKNOWN` finding `CVE-2026-97054` is in the Loki image's Go standard library `1.26.10`. Go's official advisory says versions before `1.26.11` are affected. Loki `v3.7.10` source uses `http.MaxBytesReader` in three handlers, including its frontend transport; exploitability of the required concurrent header-write race was not reproduced. No newer corrected official Loki release was available on 2026-11-17. Keep the CVE open; do not treat loopback exposure as proof of non-applicability. See [pre-release audit](pre-release-audit.md).
- Integration, scenario/persistence, reliability, alerting, privacy, and reachable Git-history audit passed in a disposable Compose project. A first cold-start API probe ran before Grafana was ready; the rerun after service readiness passed.
- Application Detail and Live Logs visual review remains pending. Browser automation reported an unavailable host and no browser inventory; no screenshots were captured. API tests are not presented as visual evidence.
- The MIT rights-holder/authority remains unconfirmed by the maintainer. Do not publish until explicit confirmation. Upstream license and attribution boundaries remain in [license audit](license-audit.md).

### Remaining release blockers

- [ ] Adopt a patched official Loki image, or complete an independently reviewed and regression-tested rebuild with Go `1.26.11` or later.
- [ ] Review Application Detail and Live Logs in a real browser, including filters, tables, Explore, and Live tail; capture genuine screenshots.
- [ ] Obtain explicit maintainer confirmation of the MIT copyright holder and licensing authority.
- [ ] Define and test a protected, off-host backup destination and recovery point expectations before claiming operational backup readiness.
- [ ] Review the final staged repository for private data and approve the release checklist.
- [ ] Obtain separate authorization before creating local `v0.1.0` tag, pushing, or publishing.

## Blocker closeout attempt — 2026-11-17

The official [`/releases/latest`](https://github.com/grafana/loki/releases/latest) page still points to Loki `v3.7.10`, built with Go `1.26.10`; the [Go advisory](https://pkg.go.dev/vuln/GO-2026-6859) says the fix is Go `1.26.11`. A same-source Loki rebuild using the official patched Go toolchain and pinned official runtime base was evaluated and attempted twice. Both builds reached `go build` and then the Docker Engine returned EOF/HTTP 500; the second attempt limited Go parallelism and GC. No final candidate image was produced or inspected, so no Trivy-by-digest, SBOM, or candidate regression result exists. Experimental Compose build wiring was reverted; Compose continues to name the official Loki 3.7.10 image.

The Docker Engine then remained in `stopping` state and its managed WSL distro was stopped. The original containers exited with 255. No volume removal or repair was run; the last successful volume inventory still showed the original project volumes. Engine recovery and a fresh volume inventory are outstanding. Do not treat the earlier restore drill as a test of this unbuilt image.

Browser automation again could not access any browser. No screenshots exist. The maintainer’s manual dashboard and Live tail checklist is recorded in [`pre-release-audit.md`](pre-release-audit.md) and [`cve-triage.md`](cve-triage.md). MIT rights-holder authority is still pending explicit maintainer confirmation.

**Decision remains NO-GO.** The Go finding has not been remediated or cleared; visual verification, artifact scan/tests, Docker Engine recovery, and MIT ownership confirmation remain release blockers. Off-host backup scheduling is a documented operational improvement for deployments that need durable recovery, not a claim made by this lab release.

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

## Visual review — 2026-11-17 (afternoon)

The built-in browser of the Claude desktop app reached the local Grafana (`127.0.0.1:3000`, local lab credentials). The four screenshots in [`screenshots/`](screenshots/) are genuine captures from this session, at an emulated 1440×900 viewport, and contain only synthetic lab traffic.

| Area | Result |
|---|---|
| Application Detail, all filters | Stats, latency percentiles, status/error series, method and path bars, slowest table and recent-requests table render with data ([screenshot](screenshots/application-detail-overview.jpg)). |
| Application Detail, app + path filter | `app-b` + `env` narrows the recent-requests table to the four matching `/app-b/.env` 404 events ([screenshot](screenshots/application-detail-path-filter-env.jpg)). |
| Live Logs table | Events render newest first with app, method, status, path, duration and source IP ([screenshot](screenshots/live-logs-table.jpg)). |
| Explore Live tail | The dashboard link opened Explore with the current filters; **Live** streamed events, and a controlled `GET /app-c/forbidden` (403) appeared in the stream within seconds ([screenshot](screenshots/explore-live-tail.jpg)). |

### Defects found

1. **Fixed — path filter with regex metacharacters.** Grafana's `${path:regex}` escapes `.` as `\.`; inside a double-quoted LogQL string that is an invalid escape, so typing `.env` or `app-b/.` turned every Loki panel of Application Detail and Live Logs into `parse error ... invalid char escape`. Commit `9bb66ba` uses backtick raw strings for the path filter (both dashboards, the Explore link and the builder) and adds a dotted-path case to the Live Logs filter test. Loki returned `400` for the old form and `200` for the new one; `python tests/verify_pipeline.py` passed with the new case (`Path with dot: 3`) and the patched dashboards were confirmed visually.
2. **Fixed — bar/table panels with a single series.** `seriesToRows` passes a single frame through unchanged, so when filters left exactly one series (for example Application Detail with `app-b` + path `env`, or Overview with one app) the category bars showed "No numeric fields found". Commit `732720b` makes the four Prometheus category bars request `format: table` (one frame with a label column) and makes the Loki path bars and slowest-request table `merge` their per-series frames, with the label as the bar category. Two intermediate attempts (`reduce`, and `labelsToFields` + `merge`) were rejected: the panel inspector showed lost or mislabeled values. The final shape was checked visually with all and single selections on Application Detail, Overview and Security, its merged values were read from the panel inspector, and `python tests/verify_pipeline.py` passed with a guard that no dashboard uses `seriesToRows`.
3. **Cosmetic.** The slowest-request table now shows `App`, `Method`, `Status`, `Path` and `Max duration (ms)` instead of overflowing raw label columns (fixed by `732720b`). Still open: the `sortBy` transform on path bars does not reorder bars by value (bars stay in label order, as before), recent-request tables show the raw `time` field next to the parsed `Time`, and stat titles truncate at narrow widths with the sidebar docked.

### Operational note

Grafana did not pick up the edited dashboard JSON from the bind mount on its own; `POST /api/admin/provisioning/dashboards/reload` applied it without restarting the container.

### Release status

Visual review of Application Detail, Live Logs and Live tail is now **done**; defects 1 and 2 are fixed and only cosmetic items remain. The release remains **NO-GO**: Loki `v3.7.10` is still the latest official release (checked 2026-11-17; Go 1.26.11 fix and grafana/loki#25118 still pending), and MIT rights-holder confirmation and the backup-scope decision are still with the maintainer.
