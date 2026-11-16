"""Verify Nginx access logs redact synthetic secrets before persistence."""
import base64
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


def load_local_env():
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    try:
        with open(env_path, encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
    except FileNotFoundError:
        pass


load_local_env()
base = os.getenv("LAB_URL", "http://127.0.0.1:8080").rstrip("/")
prom = os.getenv("PROMETHEUS_URL", "http://127.0.0.1:9090").rstrip("/")
loki = os.getenv("LOKI_URL", "http://127.0.0.1:3100").rstrip("/")


def get_json(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def query_loki(expression, start_ns):
    params = urllib.parse.urlencode({
        "query": expression,
        "start": str(start_ns),
        "end": str(time.time_ns()),
        "limit": "100",
    })
    return get_json(f"{loki}/loki/api/v1/query_range?{params}")["data"]["result"]


def counter_value():
    expression = 'nginx_http_response_count_total{app="app-a",method="POST",status="404"}'
    params = urllib.parse.urlencode({"query": expression})
    result = get_json(f"{prom}/api/v1/query?{params}")
    return sum(float(series["value"][1]) for series in result["data"]["result"])


def main():
    marker = f"PRIVACY_CANARY_{uuid.uuid4().hex}"
    route = f"/path/{marker}"
    query = urllib.parse.urlencode({"access_token": marker, "password": marker})
    url = f"{base}/app-a{route}?{query}"
    # The access log timestamp uses RFC3339 with second precision, so leave a
    # margin to include an event generated in the same second as this test.
    start_ns = time.time_ns() - 5_000_000_000
    count_before = counter_value()
    request = urllib.request.Request(
        url,
        data=b"",
        method="POST",
        headers={
            "Cookie": f"session={marker}",
            "Authorization": f"Bearer {marker}",
            "Referer": f"http://synthetic.invalid/path?credential={marker}",
            "User-Agent": f"privacy-test/{marker}",
        },
    )
    try:
        urllib.request.urlopen(request, timeout=5)
    except urllib.error.HTTPError as error:
        assert error.code == 404, "Synthetic unclassified route did not return expected 404"

    # Check the complete Nginx log directory, including rotated files, without
    # ever printing their contents or the synthetic canary.
    grep = subprocess.run(
        ["docker", "compose", "exec", "-T", "nginx", "sh", "-c",
         'for f in /var/log/nginx/app-*; do [ -f "$f" ] || continue; grep -F -q "$1" "$f" && exit 0; done; exit 1',
         "privacy-check", marker],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert grep.returncode == 1, "Synthetic canary appeared in an Nginx active or rotated access log"

    expression = '{job="nginx",app="app-a"}'
    deadline = time.time() + 45
    matching_events = []
    while time.time() < deadline:
        streams = query_loki(expression, start_ns)
        matching_events = []
        for stream in streams:
            for _, line in stream.get("values", []):
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get("method") == "POST" and event.get("status") == 404 and event.get("path") == "/app-a/_unclassified":
                    matching_events.append((line, event))
        if matching_events:
            break
        time.sleep(1)
    assert matching_events, "Sanitized synthetic request was not ingested by Loki"
    matching_lines = [line for line, _ in matching_events]
    event = matching_events[-1][1]
    assert event["app"] == "app-a" and event["method"] == "POST" and event["status"] == 404
    assert event["path"] == "/app-a/_unclassified", "Unexpected path escaped the route allowlist"
    assert {"time", "app", "remote_addr", "method", "path", "status", "request_time"} <= set(event)
    assert not ({"request", "remote_user", "http_referer", "http_user_agent"} & set(event))
    assert marker not in json.dumps(event, sort_keys=True)
    assert all(marker not in line for line in matching_lines), "Synthetic canary appeared in Loki event contents"

    # Ensure the exporter still parses the modified text format and keeps its
    # bounded metric dimensions (no source IP or arbitrary route labels).
    deadline = time.time() + 45
    while time.time() < deadline:
        if counter_value() >= count_before + 1:
            break
        time.sleep(1)
    assert counter_value() >= count_before + 1, "Exporter did not count the sanitized request"
    metric_params = urllib.parse.urlencode({"query": 'nginx_http_response_count_total{app="app-a",method="POST",status="404"}'})
    metric_series = get_json(f"{prom}/api/v1/query?{metric_params}")["data"]["result"]
    assert metric_series and all("remote_addr" not in item["metric"] and "path" not in item["metric"]
                                 for item in metric_series), "High-cardinality data appeared as Prometheus labels"
    print("OK: synthetic query/header/path secrets absent from Nginx active/rotated logs and Loki; sanitized route, metrics, and exporter parsing verified")


if __name__ == "__main__":
    main()
