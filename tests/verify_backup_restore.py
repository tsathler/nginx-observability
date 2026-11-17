"""Exercise a full Prometheus, Loki, and Grafana restore in isolated volumes.

The test makes a consistent offline copy by gracefully stopping only the three
stateful services, then restarts the original Compose stack before restoring
the archives into a disposable Compose project with loopback-only ports.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVICES = ("prometheus", "loki", "grafana")
VOLUMES = {
    "prometheus": "nginx-observability_prometheus-data",
    "loki": "nginx-observability_loki-data",
    "grafana": "nginx-observability_grafana-data",
}
PORTS = {"prometheus": 9090, "loki": 3100, "grafana": 3000}
ALPINE = "alpine:3.22@sha256:49340b346798875b5592e5d420241f2f9cfba5f47e62ebb1446a1b34734e898f"


def run(args: list[str], *, check: bool = True, capture: bool = True) -> str:
    result = subprocess.run(
        args,
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )
    if check and result.returncode:
        # Compose config may render the local Grafana password in stdout.
        # Never copy captured command output into an exception or test log.
        raise RuntimeError(f"Command failed ({result.returncode}): {args[0]} {args[1:]}")
    return result.stdout or ""


def http_json(url: str, *, auth: tuple[str, str] | None = None) -> object:
    request = urllib.request.Request(url)
    if auth:
        import base64

        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read())


def wait_http(url: str, *, auth: tuple[str, str] | None = None) -> object:
    deadline = time.monotonic() + 120
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return http_json(url, auth=auth)
        except (OSError, urllib.error.URLError, TimeoutError, ValueError) as exc:
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"Service did not become ready: {url}: {last_error}")


def wait_ok(url: str) -> str:
    deadline = time.monotonic() + 120
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return response.read().decode("utf-8", errors="replace")
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            time.sleep(2)
    raise RuntimeError(f"Service did not become ready: {url}: {last_error}")


def host_port(project: str, service: str, port: int) -> int:
    value = run(["docker", "compose", "-f", str(project_file), "-p", project, "port", service, str(port)]).strip()
    return int(value.rsplit(":", 1)[1])


project_file: Path


def parse_env() -> tuple[str, str]:
    values: dict[str, str] = {}
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    user = values.get("GRAFANA_ADMIN_USER", "admin")
    password = values.get("GRAFANA_ADMIN_PASSWORD", "")
    if not password:
        raise RuntimeError("GRAFANA_ADMIN_PASSWORD is not configured in the local .env")
    return user, password


def compose_config() -> dict:
    return json.loads(run(["docker", "compose", "config", "--format", "json"]))


def service_mounts(config: dict, service: str) -> list[dict]:
    return [
        {"type": "bind", "source": str(ROOT / item["source"]), "target": item["target"], "read_only": True}
        for item in config["services"][service].get("volumes", [])
        if item["type"] == "bind"
    ]


def make_isolated_compose(config: dict, project: str) -> dict:
    services: dict[str, dict] = {}
    for service in SERVICES:
        source = config["services"][service]
        target_path = {"prometheus": "/prometheus", "loki": "/loki", "grafana": "/var/lib/grafana"}[service]
        mounts = service_mounts(config, service)
        mounts.append({"type": "volume", "source": f"{service}-data", "target": target_path})
        item: dict = {
            "image": source["image"],
            "command": source.get("command", []),
            "volumes": mounts,
            "ports": [f"127.0.0.1::{PORTS[service]}"],
            "security_opt": ["no-new-privileges:true"],
            "cap_drop": ["ALL"],
            "restart": "no",
        }
        if source.get("environment"):
            # Use the restored Grafana database credential; don't write the
            # host secret into this disposable Compose file.
            if service != "grafana":
                item["environment"] = source["environment"]
        services[service] = item
    volumes = {
        f"{service}-data": {"name": f"{project}-{service}-data", "external": True}
        for service in SERVICES
    }
    return {"services": services, "volumes": volumes}


def backup_volume(volume: str, archive: Path, backup_dir: Path) -> None:
    run([
        "docker", "run", "--rm", "--network", "none",
        "-v", f"{volume}:/source:ro",
        "-v", f"{backup_dir.resolve()}:/backup",
        ALPINE, "sh", "-c", f"tar -czf /backup/{archive.name} -C /source .",
    ])
    if not archive.is_file() or archive.stat().st_size == 0:
        raise RuntimeError(f"Backup archive is empty: {archive.name}")
    import hashlib

    digest_builder = hashlib.sha256()
    with archive.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest_builder.update(chunk)
    digest = digest_builder.hexdigest()
    print(f"backup {archive.name}: bytes={archive.stat().st_size} sha256={digest}")


def restore_volume(project: str, service: str, archive: Path, backup_dir: Path) -> None:
    volume = f"{project}-{service}-data"
    run(["docker", "volume", "create", "--label", "com.nginx-observability.restore-test=true", volume])
    run([
        "docker", "run", "--rm", "--network", "none",
        "-v", f"{volume}:/target",
        "-v", f"{backup_dir.resolve()}:/backup:ro",
        ALPINE, "sh", "-c", f"tar -xzf /backup/{archive.name} -C /target",
    ])


def assert_original_volumes_unchanged(before: dict[str, dict]) -> None:
    after = json.loads(run(["docker", "volume", "inspect", *VOLUMES.values()]))
    current = {item["Name"]: item for item in after}
    for name, original in before.items():
        assert name in current, f"Original volume disappeared: {name}"
        assert current[name]["CreatedAt"] == original["CreatedAt"], f"Original volume was recreated: {name}"
        assert current[name].get("Mountpoint") == original.get("Mountpoint"), f"Original volume identity changed: {name}"


def main() -> None:
    global project_file
    if shutil.which("docker") is None:
        raise RuntimeError("Docker CLI is unavailable")
    config = compose_config()
    actual_volumes = {
        service: config["volumes"][next(
            v["source"] for v in config["services"][service]["volumes"] if v["type"] == "volume"
        )]["name"]
        for service in SERVICES
    }
    if actual_volumes != VOLUMES:
        raise RuntimeError(f"Compose volume names differ from safety allowlist: {actual_volumes}")
    original_meta = json.loads(run(["docker", "volume", "inspect", *VOLUMES.values()]))
    before = {item["Name"]: item for item in original_meta}
    run(["docker", "pull", ALPINE])
    run(["docker", "compose", "up", "-d"], capture=False)

    with tempfile.TemporaryDirectory(prefix="nginx-observability-restore-") as temp:
        backup_dir = Path(temp)
        stopped = False
        try:
            run(["docker", "compose", "stop", *SERVICES], capture=False)
            stopped = True
            archives = {service: backup_dir / f"{service}-data.tar.gz" for service in SERVICES}
            for service in SERVICES:
                backup_volume(VOLUMES[service], archives[service], backup_dir)
        finally:
            if stopped:
                run(["docker", "compose", "up", "-d", *SERVICES], capture=False)

        project = f"nginx-restore-{os.getpid()}"
        project_file = backup_dir / "compose.restore.json"
        project_file.write_text(json.dumps(make_isolated_compose(config, project), indent=2), encoding="utf-8")
        for service in SERVICES:
            restore_volume(project, service, archives[service], backup_dir)

        try:
            run(["docker", "compose", "-f", str(project_file), "-p", project, "up", "-d"], capture=False)
            ports = {service: host_port(project, service, PORTS[service]) for service in SERVICES}
            bases = {service: f"http://127.0.0.1:{port}" for service, port in ports.items()}
            assert "ready" in wait_ok(f"{bases['prometheus']}/-/ready").lower()
            assert "ready" in wait_ok(f"{bases['loki']}/ready").lower()
            assert wait_http(f"{bases['grafana']}/api/health") is not None

            prom_query = urllib.parse.quote("count(count_over_time(nginx_http_response_count_total[7d]))")
            prom = http_json(f"{bases['prometheus']}/api/v1/query?query={prom_query}")
            assert prom["status"] == "success" and prom["data"]["result"], "Restored Prometheus has no historical application metric series"

            now = time.time()
            query = urllib.parse.urlencode({
                "query": '{app=~"app-a|app-b|app-c"}',
                "start": str(int((now - 7 * 86400) * 1e9)),
                "end": str(int(now * 1e9)),
                "limit": "50",
                "direction": "backward",
            })
            loki = http_json(f"{bases['loki']}/loki/api/v1/query_range?{query}")
            assert loki["status"] == "success" and loki["data"]["result"], "Restored Loki has no application log streams"

            auth = parse_env()
            search = http_json(f"{bases['grafana']}/api/search?query=Nginx", auth=auth)
            names = {item.get("title") for item in search}
            expected = {"Nginx | Overview", "Nginx | Application Detail", "Nginx | Live Logs", "Nginx | Security"}
            assert expected <= names, f"Restored Grafana dashboards missing: {sorted(expected - names)}"
            data_sources = http_json(f"{bases['grafana']}/api/datasources", auth=auth)
            assert {item.get("type") for item in data_sources} >= {"prometheus", "loki"}, "Restored Grafana data sources are incomplete"
            print("restore verified: Prometheus readiness + historical metrics; Loki readiness + logs; Grafana auth + four dashboards + datasources")
        finally:
            # The project name is generated here and this compose file mounts
            # only three explicitly named disposable volumes.
            if project.startswith("nginx-restore-"):
                run(["docker", "compose", "-f", str(project_file), "-p", project, "down", "--remove-orphans"], check=False, capture=False)
                for service in SERVICES:
                    volume = f"{project}-{service}-data"
                    metadata = json.loads(run(["docker", "volume", "inspect", volume], check=False) or "[]")
                    if metadata and metadata[0].get("Labels", {}).get("com.nginx-observability.restore-test") == "true":
                        run(["docker", "volume", "rm", volume], check=False)
        assert_original_volumes_unchanged(before)
    run(["docker", "compose", "up", "-d"], capture=False)
    print("original volume identities preserved; original stack is running")


if __name__ == "__main__":
    main()
