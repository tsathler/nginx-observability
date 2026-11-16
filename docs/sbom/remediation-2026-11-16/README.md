# CVE remediation scan — 2026-11-16

Trivy `0.76.2` scanned all 11 image artifacts used by the final local Compose run. This folder contains one SPDX JSON SBOM and one raw Trivy vulnerability JSON report per image. `trivy-vulnerability-summary.json` records image IDs, repo digests, package versions, fixed versions, advisory URLs and package-finding counts. The repo digests, rather than only mutable tags, identify the scanned bytes.

**Loki scan superseded:** the Loki artifacts in this directory describe `grafana/loki:3.7.8`. The Compose runtime now uses `grafana/loki:3.7.10`; its final-digest Trivy report and SPDX are [`../loki-v3.7.10.vuln.json`](../loki-v3.7.10.vuln.json) and [`../loki-v3.7.10.spdx.json`](../loki-v3.7.10.spdx.json). See [`../../cve-triage.md`](../../cve-triage.md) for the updated two-CVE finding and WAL recovery evidence.

## Findings after remediation

Counts are package-CVE findings in the order Critical / High / Medium / Low / Unknown. A single CVE can appear in multiple packages; the five Python-derived images repeat the same base findings.

| Image | Reference used | Critical / High / Medium / Low / Unknown |
|---|---|---:|
| alert-receiver | local image, Python 3.13.18 slim Trixie + current Debian upgrades, runtime `pip`/`ensurepip` removed | 0 / 47 / 92 / 65 / 5 |
| app-a | local image, Python 3.13.18 slim Trixie + current Debian upgrades, runtime `pip`/`ensurepip` removed | 0 / 47 / 92 / 65 / 5 |
| app-b | local image, Python 3.13.18 slim Trixie + current Debian upgrades, runtime `pip`/`ensurepip` removed | 0 / 47 / 92 / 65 / 5 |
| app-c | local image, Python 3.13.18 slim Trixie + current Debian upgrades, runtime `pip`/`ensurepip` removed | 0 / 47 / 92 / 65 / 5 |
| traffic-generator | local image, Python 3.13.18 slim Trixie + current Debian upgrades, runtime `pip`/`ensurepip` removed | 0 / 47 / 92 / 65 / 5 |
| nginxlog-exporter | locally rebuilt from upstream `v1.11.0`, Go `1.27.3`, `golang.org/x/net v0.62.0` | 0 / 0 / 1 / 0 / 1 |
| Loki | `grafana/loki:3.7.8` | 0 / 7 / 21 / 5 / 3 |
| Alloy | `grafana/alloy:v1.22.0` | 0 / 0 / 19 / 4 / 2 |
| Grafana | `grafana/grafana:12.4.15` | 0 / 2 / 4 / 0 / 4 |
| Nginx | local rebuild from `nginx:1.30.6-alpine`, Alpine `libxslt` 1.1.43-r4 | 0 / 0 / 1 / 0 / 0 |
| Prometheus | `prom/prometheus:v3.16.0` | 0 / 2 / 2 / 0 / 4 |

## Comparison with the initial scan

| Component | Initial Critical / High | Current Critical / High | Explanation |
|---|---:|---:|---|
| Python-derived images (each) | 9 / 80 | 0 / 47 | Switched from Python 3.13.2 slim / Debian 12 to Python 3.13.18 slim Trixie, applied current Debian package upgrades and removed unused runtime `pip`/`ensurepip`; five package-CVE findings per image dropped. Eleven unique High IDs remain. |
| Loki | 2 / 54 | 0 / 7 | Updated 3.5.7 → 3.7.8. |
| Alloy | 2 / 71 | 0 / 0 | Updated 1.12.2 → 1.22.0. Official release notes include Go 1.27.3, `x/net` 0.62.0 and fixes for file position updates and recreated-file inode reuse. |
| nginxlog-exporter | 5 / 69 | 0 / 0 | Rebuilt upstream v1.11.0 source with Go 1.27.3 and x/net 0.62.0; the published v1.11.0 image itself still used Go 1.18.10 and had 4 Critical / 40 High in this scan. |
| Grafana | 0 / 2 | 0 / 2 | Unchanged digest; those findings remain. |
| Nginx | 0 / 3 | 0 / 0 | Rebuilt from the same `nginx:1.30.6-alpine` base after Alpine's `libxslt` package update from 1.1.43-r3 to 1.1.43-r4; rescanned the resulting local image ID. |
| Prometheus | 0 / 2 | 0 / 2 | Re-scanned the unchanged image ID. Current reports show two package findings for one unique High CVE, `CVE-2026-78661`; the earlier zero-High summary was stale and did not prove remediation. |

The initial and current scan summaries are retained at [`../trivy-vulnerability-summary.json`](../trivy-vulnerability-summary.json) and [`trivy-vulnerability-summary.json`](trivy-vulnerability-summary.json), respectively. Review each raw JSON report for the exact residual CVE, package, installed/fixed version and advisory. The current summary has been regenerated from the 11 raw image reports and current Docker image inspections.

## Interpretation and limits

Trivy confirms package or Go build-info matches. It does not establish runtime reachability, exploitability, or a false positive. The per-CVE review and rationale are in [`../../cve-triage.md`](../../cve-triage.md). The prior raw reports contained 27 unique High CVE IDs after GHSA alias deduplication; current scans contain 19 unique IDs. Eight are absent from the current images after verified `pip` removal and the `libxslt` upgrade. Zero Critical findings is a scan result, not proof of no Critical vulnerability.

The Python `apt-get upgrade` step improves the current build but resolves packages from the live Debian repository, so the build is not fully byte-for-byte reproducible. Pinning a Debian snapshot or package versions is a follow-up if stronger reproducibility is needed.

## Individual High CVE triage

[`docs/cve-triage.md`](../../cve-triage.md) records all 27 unique High CVE IDs from the previous reports, removes duplications across the five Python-derived images, maps the GHSA alias for CVE-2026-57585, and details exploit preconditions, package versions, fixes, image-specific applicability and evidence. It distinguishes eight CVEs corrected in new image IDs from 19 unique IDs still reported by the current Trivy scans. Current classification totals and the two indeterminate Loki paths are stated in that report.

The final Nginx image is `nginx-observability-nginx:1.30.6-alpine-libxslt-r4`, local image ID `sha256:e8e5fd94e3a5ec223b8a9c0b695a369e17d9fe96bf9a6da1dc7d06d0cd3f0a4a`. The other ten local image IDs were unchanged since the rescan set at 14:44 UTC-3. No volumes were removed. No VEX is issued for configuration-scoped non-applicability or indeterminate symbol reachability; corrected package versions and current per-image reports are the evidence for the fixed findings.
