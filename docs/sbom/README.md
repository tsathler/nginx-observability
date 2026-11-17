# Release image inventory and CVE scan

> **Superseded initial scan.** The SBOMs listed in the table below describe the images used before remediation (Loki `3.5.7`, Alloy `v1.12.2`, exporter `v1.9.2`) and are kept as historical evidence. The current Compose images (Loki `3.7.10`, Alloy `v1.22.0`, exporter rebuilt from upstream `v1.11.0`) are covered by [`remediation-2026-11-16/`](remediation-2026-11-16/README.md) and, for Loki, by [`loki-v3.7.10.spdx.json`](loki-v3.7.10.spdx.json) and [`loki-v3.7.10.vuln.json`](loki-v3.7.10.vuln.json).

Audit date: **2026-11-16**. This directory contains SPDX SBOMs and the Trivy package-finding summary for the image digests used by the local Compose environment on that date.

The scan used Trivy `0.76.2`, downloaded from the official [Trivy v0.76.2 GitHub release](https://github.com/aquasecurity/trivy/releases/tag/v0.76.2). The Windows ZIP SHA-256 was verified against the release checksum file: `691f737a7e5566a673c3a74dab9160552ec32101e953b659e5c77443d16dddb6`. The vulnerability DB was refreshed on 2026-11-16. Docker Scout CLI was also checked, but it required a Docker account login; no login was performed.

## Artifacts

| Image reference | SPDX SBOM |
|---|---|
| `nginx:1.30.6-alpine` | [nginx-1.30.6-alpine.spdx.json](nginx-1.30.6-alpine.spdx.json) |
| `prom/prometheus:v3.16.0` | [prometheus-v3.16.0.spdx.json](prometheus-v3.16.0.spdx.json) |
| `grafana/grafana:12.4.15` | [grafana-12.4.15.spdx.json](grafana-12.4.15.spdx.json) |
| `grafana/loki:3.5.7` | [loki-3.5.7.spdx.json](loki-3.5.7.spdx.json) |
| `grafana/alloy:v1.12.2` | [alloy-v1.12.2.spdx.json](alloy-v1.12.2.spdx.json) |
| `quay.io/martinhelmich/prometheus-nginxlog-exporter:v1.9.2` | [nginxlog-exporter-v1.9.2.spdx.json](nginxlog-exporter-v1.9.2.spdx.json) |
| `nginx-observability-app-a:latest` | [app-a.spdx.json](app-a.spdx.json) |
| `nginx-observability-app-b:latest` | [app-b.spdx.json](app-b.spdx.json) |
| `nginx-observability-app-c:latest` | [app-c.spdx.json](app-c.spdx.json) |
| `nginx-observability-traffic-generator:latest` | [traffic-generator.spdx.json](traffic-generator.spdx.json) |
| `nginx-observability-alert-receiver:latest` | [alert-receiver.spdx.json](alert-receiver.spdx.json) |

[`trivy-vulnerability-summary.json`](trivy-vulnerability-summary.json) records each package-level finding, severity, installed/fixed version, advisory link, image digest, and counts. It is compacted from raw Trivy JSON using [`scripts/summarize_trivy_reports.py`](../../scripts/summarize_trivy_reports.py). The original per-image raw scanner JSON was kept in the user's temporary directory during this audit and is not committed.

## Scope and interpretation

The scan reads package and binary metadata from the image. A reported package/version is evidence of a dependency match, not proof an attacker can reach the vulnerable code. Trivy's image scan did not do dynamic exploit testing or establish call-path reachability. It did not identify any result as a verified false positive, and this repository contains no accepted VEX dispositions. A CVE may appear for more than one package in a single image; Python base findings repeat across five locally built images. The counts in the audit are package findings, not unique exploitable vulnerabilities.

The image digests here identify the local artifacts scanned. Compose uses version tags rather than immutable digests, so a later pull/build may produce different bytes. Re-run the scan and regenerate SBOMs for the actual release digests. This inventory is not a complete license/legal opinion and does not establish production readiness.

To regenerate the compact summary from raw Trivy JSON reports:

```shell
python scripts/summarize_trivy_reports.py <directory-with-raw-trivy-json> docs/sbom/trivy-vulnerability-summary.json
```
