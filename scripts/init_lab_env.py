"""Create ignored local lab settings and a random Grafana administrator password."""
from pathlib import Path
import secrets
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
EXAMPLE_FILE = ROOT / ".env.example"


def read_values(path: Path) -> dict[str, str]:
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"\'')
    return values


def reset_running_admin() -> None:
    running = subprocess.run(["docker", "compose", "ps", "--status", "running", "--quiet", "grafana"],
                             cwd=ROOT, capture_output=True, text=True)
    if running.returncode or not running.stdout.strip():
        return
    subprocess.run(["docker", "compose", "exec", "-T", "grafana", "sh", "-c",
                    'grafana cli admin reset-admin-password "$GF_SECURITY_ADMIN_PASSWORD"'],
                   cwd=ROOT, check=True, stdout=subprocess.DEVNULL)


def main() -> int:
    if ENV_FILE.exists():
        values = read_values(ENV_FILE)
        if not values.get("GRAFANA_ADMIN_PASSWORD"):
            print(".env exists but has no GRAFANA_ADMIN_PASSWORD; set it locally and rerun.", file=sys.stderr)
            return 1
        reset_running_admin()
        print("Local .env already exists; preserved without displaying credentials.")
        return 0

    content = EXAMPLE_FILE.read_text(encoding="utf-8")
    content = "\n".join(line for line in content.splitlines()
                       if not line.startswith("GRAFANA_ADMIN_PASSWORD="))
    password = secrets.token_urlsafe(36)
    ENV_FILE.write_text(content.rstrip() + f"\nGRAFANA_ADMIN_PASSWORD={password}\n", encoding="utf-8")
    try:
        ENV_FILE.chmod(0o600)
    except OSError:
        # On Windows, the file inherits the current user's directory ACL.
        pass
    reset_running_admin()
    print("Created ignored .env with a random Grafana password; the credential was not displayed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
