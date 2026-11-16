# CVE remediation scan — 2026-11-16

Trivy `0.76.2` scanned all 11 image artifacts used by the final local Compose run. This folder contains one SPDX JSON SBOM and one raw Trivy vulnerability JSON report per image. `trivy-vulnerability-summary.json` records image IDs, repo digests, package versions, fixed versions, advisory URLs and package-finding counts. The repo digests, rather than only mutable tags, identify the scanned bytes.

## Findings after remediation

Counts are package-CVE findings in the order Critical / High / Medium / Low / Unknown. A single CVE can appear in multiple packages; the five Python-derived images repeat the same base findings.

| Image | Reference used | Critical / High / Medium / Low / Unknown |
|---|---|---:|
| alert-receiver | local image, Python 3.13.18 slim Trixie + current Debian upgrades | 0 / 52 / 94 / 66 / 5 |
| app-a | local image, Python 3.13.18 slim Trixie + current Debian upgrades | 0 / 52 / 94 / 66 / 5 |
| app-b | local image, Python 3.13.18 slim Trixie + current Debian upgrades | 0 / 52 / 94 / 66 / 5 |
| app-c | local image, Python 3.13.18 slim Trixie + current Debian upgrades | 0 / 52 / 94 / 66 / 5 |
| traffic-generator | local image, Python 3.13.18 slim Trixie + current Debian upgrades | 0 / 52 / 94 / 66 / 5 |
| nginxlog-exporter | locally rebuilt from upstream `v1.11.0`, Go `1.27.3`, `golang.org/x/net v0.62.0` | 0 / 0 / 1 / 0 / 1 |
| Loki | `grafana/loki:3.7.8` | 0 / 7 / 21 / 5 / 3 |
| Alloy | `grafana/alloy:v1.22.0` | 0 / 0 / 19 / 4 / 2 |
| Grafana | `grafana/grafana:12.4.15` | 0 / 2 / 4 / 0 / 4 |
| Nginx | `nginx:1.30.6-alpine` | 0 / 3 / 2 / 0 / 0 |
| Prometheus | `prom/prometheus:v3.16.0` | 0 / 0 / 1 / 0 / 1 |

## Comparison with the initial scan

| Component | Initial Critical / High | Current Critical / High | Explanation |
|---|---:|---:|---|
| Python-derived images (each) | 9 / 80 | 0 / 52 | Switched from Python 3.13.2 slim / Debian 12 to Python 3.13.18 slim Trixie and applied current signed Debian package upgrades. High findings remain and require triage/remediation. |
| Loki | 2 / 54 | 0 / 7 | Updated 3.5.7 → 3.7.8. |
| Alloy | 2 / 71 | 0 / 0 | Updated 1.12.2 → 1.22.0. Official release notes include Go 1.27.3, `x/net` 0.62.0 and fixes for file position updates and recreated-file inode reuse. |
| nginxlog-exporter | 5 / 69 | 0 / 0 | Rebuilt upstream v1.11.0 source with Go 1.27.3 and x/net 0.62.0; the published v1.11.0 image itself still used Go 1.18.10 and had 4 Critical / 40 High in this scan. |
| Grafana | 0 / 2 | 0 / 2 | Unchanged digest; those findings remain. |
| Nginx | 0 / 3 | 0 / 3 | Unchanged digest; those findings remain. |
| Prometheus | 0 / 2 | 0 / 0 | Unchanged digest. The current Trivy database no longer reports the earlier High findings; this is a feed/report change, not an image update or demonstrated remediation. |

The initial and current scan summaries are retained at [`../trivy-vulnerability-summary.json`](../trivy-vulnerability-summary.json) and [`trivy-vulnerability-summary.json`](trivy-vulnerability-summary.json), respectively. Review each raw JSON report for the exact residual CVE, package, installed/fixed version and advisory.

## Interpretation and limits

Trivy confirms package or Go build-info matches. It does not establish runtime reachability, exploitability, or a false positive. No candidate was marked not-applicable or dismissed. Zero Critical findings is a scan result, not proof of no Critical vulnerability. High findings remain across Python-derived images, Loki, Alloy, Grafana and Nginx; they must be reviewed against vendor advisories and applicability before release. Prometheus's earlier High-to-zero change is not attributed to remediation because its digest did not change.

The Python `apt-get upgrade` step improves the current build but resolves packages from the live Debian repository, so the build is not fully byte-for-byte reproducible. Pinning a Debian snapshot or package versions is a follow-up if stronger reproducibility is needed.
