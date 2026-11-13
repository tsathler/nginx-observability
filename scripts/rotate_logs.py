"""Rotate Nginx access log files by rename and ask Nginx to reopen them.

Run periodically from the host while the Compose lab is running. No Docker socket
is mounted into any container and the active files are never copied/truncated.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
LOG_FILES = ("app-a.json", "app-a.log", "app-b.json", "app-b.log", "app-c.json", "app-c.log")


def load_local_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            os.environ.setdefault(name.strip(), value.strip().strip('"\''))


def rotate_once(max_bytes: int, keep: int) -> str:
    shell_lines = [
        "set -eu",
        f"MAX_BYTES={max_bytes}",
        f"KEEP={keep}",
        "ROTATED=0",
        "for name in " + " ".join(LOG_FILES) + "; do",
        '  file="/var/log/nginx/$name"',
        '  [ -f "$file" ] || continue',
        '  for archive in "$file".[0-9]*; do',
        '    [ -e "$archive" ] || continue',
        '    suffix=${archive##*.}',
        '    case "$suffix" in *[!0-9]*) continue ;; esac',
        '    [ "$suffix" -le "$KEEP" ] || rm -f "$archive"',
        "  done",
        '  size=$(wc -c < "$file" | tr -d " ")',
        '  [ "$size" -ge "$MAX_BYTES" ] || continue',
        '  rm -f "$file.$KEEP"',
        '  index=$((KEEP - 1))',
        '  while [ "$index" -ge 1 ]; do',
        '    [ ! -e "$file.$index" ] || mv -f "$file.$index" "$file.$((index + 1))"',
        '    index=$((index - 1))',
        "  done",
        '  mv -f "$file" "$file.1"',
        '  ROTATED=$((ROTATED + 1))',
        "done",
        'if [ "$ROTATED" -gt 0 ]; then nginx -s reopen; printf "rotated:%s\\n" "$ROTATED"; else printf "rotated:0\\n"; fi',
    ]
    command = ["docker", "compose", "exec", "-T", "nginx", "sh", "-c", "\n".join(shell_lines)]
    result = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def main() -> int:
    load_local_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-bytes", type=int, default=int(os.getenv("NGINX_LOG_ROTATE_BYTES", "16777216")))
    parser.add_argument("--keep", type=int, default=int(os.getenv("NGINX_LOG_ROTATE_KEEP", "3")))
    parser.add_argument("--watch", action="store_true", help="check periodically instead of running once")
    parser.add_argument("--interval", type=int, default=60, help="watch interval in seconds")
    args = parser.parse_args()
    if args.max_bytes < 1 or not 1 <= args.keep <= 20 or args.interval < 1:
        parser.error("max-bytes and interval must be positive; keep must be between 1 and 20")
    while True:
        print(rotate_once(args.max_bytes, args.keep), flush=True)
        if not args.watch:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
