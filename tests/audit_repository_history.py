"""Read-only scan of reachable Git history for common secret/data artifacts."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SECRET_PATTERNS = {
    "AWS access key": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "GitHub token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "credential URL": re.compile(rb"https?://[^/\s:@]+:[^/\s@]+@", re.IGNORECASE),
    "literal credential assignment": re.compile(
        rb"(?im)^\s*(?:password|client_secret|api[_-]?key|access[_-]?token|secret)"
        rb"\s*[:=]\s*[\"']?([A-Za-z0-9+/=_-]{24,})"
    ),
}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".log", ".db", ".sqlite", ".sqlite3"}


def git(*args: str) -> bytes:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True)
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {args[0]} failed: {detail}")
    return result.stdout


def inspect_history() -> list[str]:
    findings: set[str] = set()
    blob_cache: dict[str, bytes] = {}
    commits = git("rev-list", "--all").decode("ascii").splitlines()
    for commit in commits:
        entries = git("ls-tree", "-rz", "--full-tree", commit).split(b"\0")
        for entry in entries:
            if not entry:
                continue
            metadata, raw_path = entry.split(b"\t", 1)
            mode, object_type, object_id = metadata.split()
            if object_type != b"blob":
                continue
            path = raw_path.decode("utf-8", errors="replace")
            name = Path(path).name.lower()
            if (name.startswith(".env") and name != ".env.example") or Path(name).suffix in SENSITIVE_SUFFIXES:
                findings.add(f"{commit[:12]}:{path} (sensitive artifact path)")

            blob_id = object_id.decode("ascii")
            if blob_id not in blob_cache:
                blob_cache[blob_id] = git("cat-file", "blob", blob_id)
            blob = blob_cache[blob_id]
            for category, pattern in SECRET_PATTERNS.items():
                if pattern.search(blob):
                    findings.add(f"{commit[:12]}:{path} ({category})")
    return sorted(findings)


def main() -> int:
    findings = inspect_history()
    if findings:
        print("Potential repository-history findings (values are never printed):")
        print("\n".join(findings))
        return 1
    print("OK: scanned all reachable Git commits; no matching secrets, corporate markers, or sensitive artifact paths found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
