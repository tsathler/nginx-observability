#!/usr/bin/env python3
"""Create a compact audit summary from Trivy JSON image scan reports."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")


def summarize(path: Path) -> dict[str, object]:
    report = json.loads(path.read_text(encoding="utf-8"))
    metadata = report.get("Metadata") or {}
    findings: list[dict[str, str]] = []
    counts: Counter[str] = Counter()
    unique_ids: Counter[str] = Counter()

    for result in report.get("Results") or []:
        target = result.get("Target", "")
        for vuln in result.get("Vulnerabilities") or []:
            severity = (vuln.get("Severity") or "UNKNOWN").upper()
            counts[severity] += 1
            unique_ids[severity + "\0" + (vuln.get("VulnerabilityID") or "")] = 1
            findings.append(
                {
                    "id": vuln.get("VulnerabilityID") or "",
                    "severity": severity,
                    "package": vuln.get("PkgName") or "",
                    "installedVersion": vuln.get("InstalledVersion") or "",
                    "fixedVersion": vuln.get("FixedVersion") or "",
                    "target": target,
                    "status": vuln.get("Status") or "unspecified",
                    "advisory": vuln.get("PrimaryURL") or "",
                    "applicabilityAssessment": "not evaluated; package/version match is not proof of exploitability or a false positive",
                }
            )

    for severity in SEVERITIES:
        counts.setdefault(severity, 0)

    os_info = metadata.get("OS") or {}
    return {
        "artifact": report.get("ArtifactName", ""),
        "artifactType": report.get("ArtifactType", ""),
        "createdAt": report.get("CreatedAt", ""),
        "imageId": metadata.get("ImageID", ""),
        "repoTags": metadata.get("RepoTags") or [],
        "repoDigests": metadata.get("RepoDigests") or [],
        "platform": metadata.get("ImageConfig", {}).get("architecture", ""),
        "os": {"family": os_info.get("Family", ""), "name": os_info.get("Name", "")},
        "countsBySeverity": dict(counts),
        "uniqueVulnerabilityIdsBySeverity": {
            severity: len({key.split("\0", 1)[1] for key in unique_ids if key.startswith(severity + "\0")})
            for severity in SEVERITIES
        },
        "findingCount": len(findings),
        "findings": sorted(findings, key=lambda item: (item["severity"], item["id"], item["package"])),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports_dir", type=Path, help="directory containing Trivy *.vuln.json files")
    parser.add_argument("output", type=Path, help="output JSON summary path")
    args = parser.parse_args()

    reports = sorted(args.reports_dir.glob("*.vuln.json"))
    if not reports:
        raise SystemExit(f"No *.vuln.json reports in {args.reports_dir}")

    summary = {
        "scanner": "Trivy",
        "scannerVersion": "0.76.2",
        "scanScope": "container image vulnerabilities; applicability was not evaluated by the scanner",
        "reports": [summarize(path) for path in reports],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(reports)} image summaries to {args.output}")


if __name__ == "__main__":
    main()
