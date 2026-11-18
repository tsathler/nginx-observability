"""Exercise Loki WAL persistence in a separate Compose project and named volume."""

import json
import re
import os
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "loki-persistence" / "compose.yaml"
PROJECT = "nginxobs-loki-persist-regression"
VOLUME = "nginx-observability_loki-persistence-regression-data"
PORT = int(os.getenv("LOKI_PERSISTENCE_TEST_PORT", "13100"))
BASE_URL = f"http://127.0.0.1:{PORT}"
COMPOSE = ["docker", "compose", "--project-name", PROJECT, "--file", str(FIXTURE)]
POLL_SECONDS = 0.5


def run(command, *, cwd=ROOT, timeout=150):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(
            f"Command failed ({result.returncode}): {' '.join(map(str, command))}\n"
            f"{result.stderr.strip()}"
        )
    return result.stdout.strip()


def compose(*args, timeout=150):
    return run([*COMPOSE, *args], timeout=timeout)


def main_project_state():
    ids = run([
        "docker", "ps", "-aq",
        "--filter", "label=com.docker.compose.project=nginx-observability",
    ]).splitlines()
    if not ids:
        return ()
    containers = json.loads(run(["docker", "inspect", *ids]))
    return tuple(sorted((item["Id"], item["State"]["Status"], item["State"]["StartedAt"])
                        for item in containers))


def free_test_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", PORT))
        except OSError as error:
            raise RuntimeError(
                f"Isolated Loki test port 127.0.0.1:{PORT} is occupied; "
                "set LOKI_PERSISTENCE_TEST_PORT to an unused loopback port."
            ) from error


def open_json(url, *, data=None, method=None):
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data is not None else {},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        raw = response.read()
        return response.status, json.loads(raw) if raw else None


def wait_for(predicate, description, timeout=45):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except (OSError, urllib.error.URLError, json.JSONDecodeError, KeyError) as error:
            last_error = error
        time.sleep(POLL_SECONDS)
    detail = f"; last error: {last_error}" if last_error else ""
    raise AssertionError(f"Timed out waiting for {description}{detail}")


def ready():
    with urllib.request.urlopen(BASE_URL + "/ready", timeout=3) as response:
        return response.status == 200 and response.read().strip() == b"ready"


def metric_samples(name):
    with urllib.request.urlopen(BASE_URL + "/metrics", timeout=5) as response:
        lines = response.read().decode("utf-8").splitlines()
    samples = []
    for line in lines:
        if not line.startswith(name + "{"):
            continue
        labels_text, value_text = line.split("}", 1)
        labels = {}
        for item in labels_text.split("{", 1)[1].split(","):
            key, value = item.split("=", 1)
            labels[key] = value.strip('"')
        samples.append((labels, float(value_text.strip())))
    return samples


def metric_sum(name):
    return sum(value for _, value in metric_samples(name))


def event_timestamp_ns():
    timestamp_ns = time.time_ns()
    seconds, nanos = divmod(timestamp_ns, 1_000_000_000)
    timestamp = datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return timestamp_ns, f"{timestamp}.{nanos:09d}Z"


def push_event(path):
    timestamp_ns, timestamp = event_timestamp_ns()
    event = {
        "time": timestamp,
        "app": "app-a",
        "method": "GET",
        "path": path,
        "status": 404,
        "request_time": 0.012,
    }
    line = json.dumps(event, separators=(",", ":"), sort_keys=True)
    payload = {
        "streams": [{
            "stream": {"job": "nginx", "app": "app-a"},
            "values": [[str(timestamp_ns), line, {
                "method": "GET",
                "status": "404",
                "path": path,
            }]],
        }],
    }
    status, _ = open_json(
        BASE_URL + "/loki/api/v1/push",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
    )
    assert status == 204, f"Loki push returned HTTP {status}"
    return timestamp_ns, event, line


def query_event(path, timestamp_ns):
    expression = (
        '{job="nginx",app="app-a"}'
        ' | method="GET" | status="404" | path="' + path + '"'
    )
    params = urllib.parse.urlencode({
        "query": expression,
        "start": str(timestamp_ns - 2_000_000_000),
        "end": str(timestamp_ns + 2_000_000_000),
        "limit": "20",
        "direction": "forward",
    })
    _, result = open_json(BASE_URL + "/loki/api/v1/query_range?" + params)
    assert result["status"] == "success", f"LogQL query failed for {path}"
    return [
        (int(timestamp), line)
        for stream in result["data"]["result"]
        for timestamp, line in stream["values"]
    ]


def assert_event(path, timestamp_ns, expected_event, expected_line, phase):
    rows = query_event(path, timestamp_ns)
    exact = [(timestamp, line) for timestamp, line in rows
             if timestamp == timestamp_ns and line == expected_line]
    assert len(exact) == 1, (
        f"{phase}: expected exactly one event with the original body/timestamp for {path}; "
        f"got {len(exact)} exact rows from {len(rows)} query rows"
    )
    assert json.loads(exact[0][1]) == expected_event, f"{phase}: event body changed for {path}"


def assert_isolated_volume():
    container_id = compose("ps", "-q", "loki")
    assert container_id, "Isolated Loki container was not created"
    container = json.loads(run(["docker", "inspect", container_id]))[0]
    project = container.get("Config", {}).get("Labels", {}).get("com.docker.compose.project")
    assert project == PROJECT, f"Unexpected Compose project on test container: {project}"
    mounts = {mount["Destination"]: mount.get("Name") for mount in container.get("Mounts", [])}
    assert mounts.get("/loki") == VOLUME, f"Test data volume is not isolated: {mounts.get('/loki')}"
    assert mounts.get("/loki") != "nginx-observability_loki-data"


def assert_primary_mitigation_declared():
    loki_config = (ROOT / "config" / "loki" / "config.yml").read_text(encoding="utf-8")
    required_wal = (
        "ingester:\n  wal:\n    enabled: true\n    dir: /loki/wal\n"
        "    checkpoint_duration: 5m\n    flush_on_shutdown: true\n"
    )
    assert required_wal in loki_config, "Primary Loki config lost explicit graceful WAL flush settings"
    compose_config = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    loki_service = compose_config.split("  loki:\n", 1)[1].split("  alloy:\n", 1)[0]
    assert "stop_grace_period: 2m" in loki_service, "Primary Loki grace period is missing"


def compose_config_text(service):
    compose_config = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    return compose_config.split(f"  {service}:\n", 1)[1].split("  alloy:\n", 1)[0]


def verify_isolated_persistence():
    before_main = main_project_state()
    assert_primary_mitigation_declared()
    compose("config", "--quiet")
    config = json.loads(compose("config", "--format", "json"))
    service = config["services"]["loki"]
    primary_image = re.search(r"^    image: (\S+)$", compose_config_text("loki"), re.M).group(1)
    assert service["image"] == primary_image, (service["image"], primary_image)
    assert service.get("stop_grace_period") in {"2m", "2m0s", "120s"}, \
        service.get("stop_grace_period")
    assert VOLUME in [volume.get("name") for volume in config["volumes"].values()]

    # Stop only a prior instance of this dedicated test project, never the main stack.
    if compose("ps", "-q", "loki"):
        compose("stop", "loki", timeout=150)
    free_test_port()

    running = False
    try:
        compose("up", "-d", "--no-build", "loki", timeout=90)
        running = True
        assert_isolated_volume()
        wait_for(ready, "isolated Loki readiness")

        initial_flushed = metric_sum("loki_ingester_chunks_flushed_total")
        first_path = "/__loki_persist_" + uuid.uuid4().hex + "_first"
        first_ts, first_event, first_line = push_event(first_path)
        wait_for(lambda: bool(query_event(first_path, first_ts)), "first marker query before flush")
        wait_for(
            lambda: metric_sum("loki_ingester_chunks_flushed_total") > initial_flushed
            and metric_sum("loki_ingester_memory_streams") == 0,
            "first low-volume stream flush and eviction",
            timeout=30,
        )
        assert_event(first_path, first_ts, first_event, first_line, "before restart")

        second_path = "/__loki_persist_" + uuid.uuid4().hex + "_recreated"
        second_ts, second_event, second_line = push_event(second_path)
        wait_for(
            lambda: metric_sum("loki_ingester_memory_streams") > 0,
            "recreated low-volume stream",
        )
        assert_event(second_path, second_ts, second_event, second_line, "before restart")

        # Compose stop sends SIGTERM and waits up to the configured 120-second grace period.
        compose("stop", "loki", timeout=150)
        running = False
        compose("start", "loki", timeout=90)
        running = True
        wait_for(ready, "isolated Loki readiness after graceful restart", timeout=60)
        assert_event(first_path, first_ts, first_event, first_line, "after graceful restart")
        assert_event(second_path, second_ts, second_event, second_line, "after graceful restart")
        print(
            "OK: isolated Loki (primary image) graceful restart preserved both unique JSON events, "
            "exact timestamps, and structured metadata after stream flush/removal/recreation."
        )
    finally:
        if running:
            compose("stop", "loki", timeout=150)
        after_main = main_project_state()
        if after_main != before_main:
            raise AssertionError("Main nginx-observability container state changed during isolated test")
        print(f"Main Compose containers unchanged; retained isolated volume: {VOLUME}")


if __name__ == "__main__":
    verify_isolated_persistence()
