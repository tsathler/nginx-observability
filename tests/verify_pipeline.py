"""Verify request routing, metrics, logs, Grafana provisioning, and optional persistence."""
import argparse
import base64
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

def load_local_env():
    """Read ignored Compose .env values without printing them or overriding process env."""
    env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    try:
        with open(env_file, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip().strip('"\''))
    except FileNotFoundError:
        pass


load_local_env()
base = os.getenv("LAB_URL", "http://127.0.0.1:8080").rstrip("/")
prom = os.getenv("PROMETHEUS_URL", "http://127.0.0.1:9090").rstrip("/")
loki = os.getenv("LOKI_URL", "http://127.0.0.1:3100").rstrip("/")
grafana = os.getenv("GRAFANA_URL", "http://127.0.0.1:3000").rstrip("/")
grafana_user = os.getenv("GRAFANA_ADMIN_USER", "admin")
grafana_password = os.getenv("GRAFANA_ADMIN_PASSWORD", "")
prom_retention_time = os.getenv("PROMETHEUS_RETENTION_TIME", "7d")
prom_retention_size = os.getenv("PROMETHEUS_RETENTION_SIZE", "1GB")
loki_retention_period = os.getenv("LOKI_RETENTION_PERIOD", "168h")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


no_redirect = urllib.request.build_opener(NoRedirect)


def request_status(url):
    try:
        with no_redirect.open(url, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def open_grafana(request, timeout=10):
    if not grafana_password:
        raise AssertionError("Grafana password is unavailable; run python scripts/init_lab_env.py")
    authorization = base64.b64encode(f"{grafana_user}:{grafana_password}".encode()).decode()
    request.add_header("Authorization", f"Basic {authorization}")
    return urllib.request.urlopen(request, timeout=timeout)


def get_json(url):
    try:
        request = urllib.request.Request(url)
        opener = open_grafana if url.startswith(grafana + "/") else urllib.request.urlopen
        with opener(request, timeout=5) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise AssertionError(f"HTTP {error.code} from {url}: {error.read().decode(errors='replace')}") from error


def prom_query(expression):
    query = urllib.parse.urlencode({"query": expression})
    result = get_json(f"{prom}/api/v1/query?{query}")
    assert result["status"] == "success", result
    return result["data"]["result"]


def grafana_prom_frames(expression, legend_format="{{app}}"):
    body = {
        "queries": [{"refId": "A", "datasource": {"type": "prometheus", "uid": "prometheus"},
                     "expr": expression, "instant": True, "range": False, "format": "time_series",
                      "legendFormat": legend_format, "intervalMs": 10000, "maxDataPoints": 100}],
        "from": "now-15m", "to": "now",
    }
    request = urllib.request.Request(f"{grafana}/api/ds/query", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
    with open_grafana(request, timeout=10) as response:
        result = json.load(response)
    assert result["results"]["A"]["status"] == 200, result
    return result["results"]["A"]["frames"]


def grafana_loki_frames(expression, query_type="range", legend_format=None, max_lines=20):
    target = {"refId": "A", "datasource": {"type": "loki", "uid": "loki"},
              "expr": expression, "queryType": query_type, "maxLines": max_lines}
    if legend_format:
        target["legendFormat"] = legend_format
    body = {
        "queries": [target],
        "from": "now-15m", "to": "now",
    }
    request = urllib.request.Request(f"{grafana}/api/ds/query", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
    with open_grafana(request, timeout=10) as response:
        result = json.load(response)
    assert result["results"]["A"]["status"] == 200, result
    return result["results"]["A"]["frames"]


def loki_instant(expression, eval_time_ns=None):
    params = {"query": expression, "limit": "100"}
    if eval_time_ns is not None:
        params["time"] = str(eval_time_ns / 1_000_000_000)
    result = get_json(f"{loki}/loki/api/v1/query?{urllib.parse.urlencode(params)}")
    assert result.get("status") == "success", (expression, result)
    return result["data"]["result"]


def prom_scalar(expression):
    result = prom_query(expression)
    assert result, f"Prometheus returned no value for {expression}"
    return float(result[0]["value"][1])


def target_scraped_after(job, epoch):
    return any(float(item["value"][0]) >= epoch and item["value"][1] == "1"
               for item in prom_query(f'up{{job="{job}"}}'))


def loki_query(expression, start_ns=None, end_ns=None, limit=200):
    end_ns = end_ns or time.time_ns()
    params = {
        "query": expression,
        "start": str(start_ns or end_ns - 600_000_000_000),
        "end": str(end_ns),
        "limit": str(limit),
    }
    return get_json(f"{loki}/loki/api/v1/query_range?{urllib.parse.urlencode(params)}")["data"]["result"]


def wait_for(predicate, message, timeout=90):
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            if predicate():
                return
        except (OSError, urllib.error.URLError, KeyError, AssertionError) as error:
            last_error = error
        time.sleep(2)
    suffix = f" (last error: {last_error})" if last_error else ""
    raise AssertionError(message + suffix)


def verify_platform_security():
    """Check local-only publication, Grafana authentication, and Compose isolation."""
    assert grafana_password, "Grafana password is missing from environment/.env"
    completed = subprocess.run(["docker", "compose", "config", "--format", "json"],
                               check=True, capture_output=True, text=True)
    config = json.loads(completed.stdout)
    services = config["services"]
    allowed_published = {"nginx", "prometheus", "loki", "grafana"}
    for name, service in services.items():
        for port in service.get("ports", []):
            assert name in allowed_published, f"Unexpected host-published service: {name}"
            assert port.get("host_ip") in {"127.0.0.1", "::1"}, f"{name} published outside loopback"
    for name in ("app-a", "app-b", "app-c", "traffic-generator", "nginxlog-exporter", "alloy"):
        assert not services[name].get("ports"), f"{name} unexpectedly publishes a host port"
    assert not services["alert-receiver"].get("ports"), "Local webhook receiver unexpectedly publishes a host port"
    assert set(services["alert-receiver"]["networks"]) == {"alerts"}, \
        "Local webhook receiver must remain isolated on the internal alerts network"

    grafana_env = services["grafana"]["environment"]
    assert grafana_env["GF_AUTH_ANONYMOUS_ENABLED"] == "false"
    assert grafana_env["GF_USERS_ALLOW_SIGN_UP"] == "false"
    assert grafana_env["GF_SECURITY_ADMIN_PASSWORD"] == grafana_password
    assert "GF_AUTH_DISABLE_LOGIN_FORM" not in grafana_env

    for network in ("frontend", "metrics", "logs", "alerts"):
        assert config["networks"][network].get("internal") is True, f"{network} is not internal"
    assert set(services["grafana"]["networks"]) == {"metrics", "logs", "host-access", "alerts"}
    assert "alerts" not in services["prometheus"]["networks"]
    assert "frontend" not in services["prometheus"]["networks"]
    assert "frontend" not in services["loki"]["networks"]
    assert "host-access" not in services["traffic-generator"]["networks"]
    assert "host-access" not in services["app-a"]["networks"]
    assert all("no-new-privileges:true" in service.get("security_opt", [])
               for service in services.values()), "A service lacks no-new-privileges"

    status = request_status(f"{grafana}/api/datasources")
    assert status == 401, f"Unauthenticated Grafana API returned HTTP {status}, expected 401"
    sources = get_json(f"{grafana}/api/datasources")
    assert {source["name"] for source in sources} >= {"Prometheus", "Loki"}

    root = os.path.dirname(os.path.dirname(__file__))
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True,
                             capture_output=True).stdout.decode().split("\0")
    tracked = {path.replace("\\", "/") for path in tracked if path}
    assert ".env" not in tracked, "Local .env is tracked"
    assert not any(path.lower().endswith((".pem", ".key", ".p12", ".pfx")) for path in tracked), \
        "A private key/certificate file is tracked"
    hardcoded_secret = re.compile(
        r"(?i)\b(?:password|passwd|client_secret|api[_-]?token)\b\s*[:=]\s*['\"](?!\$)[^'\"]{8,}['\"]")
    for relative in tracked:
        candidate = os.path.join(root, relative.replace("/", os.sep))
        try:
            content = open(candidate, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        assert not hardcoded_secret.search(content), f"Possible hardcoded credential in tracked file: {relative}"
    example = open(os.path.join(root, ".env.example"), encoding="utf-8").read()
    assert re.search(r"(?m)^GRAFANA_ADMIN_PASSWORD=\s*$", example), \
        ".env.example contains a non-empty Grafana password"
    ignore = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=root)
    assert ignore.returncode == 0, ".env is not ignored by Git"
    return {"ports_loopback_only": True, "grafana_unauthorized_http": status,
            "networks_internal": True, "tracked_env_or_key_files": False}


def verify_retention_configuration():
    flags = get_json(f"{prom}/api/v1/status/flags")["data"]
    def duration_seconds(value):
        units = {"ms": .001, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "y": 31536000}
        parts = re.findall(r"(\d+(?:\.\d+)?)(ms|[smhdwy])", value)
        assert parts and "".join(number + unit for number, unit in parts) == value
        return sum(float(number) * units[unit] for number, unit in parts)

    def size_bytes(value):
        units = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3,
                 "TB": 1024**4, "PB": 1024**5, "EB": 1024**6,
                 "KIB": 1024, "MIB": 1024**2, "GIB": 1024**3,
                 "TIB": 1024**4, "PIB": 1024**5, "EIB": 1024**6}
        match = re.fullmatch(r"(\d+(?:\.\d+)?)(B|KB|MB|GB|TB|PB|EB|KiB|MiB|GiB|TiB|PiB|EiB)", value, re.IGNORECASE)
        assert match, f"Unsupported Prometheus retention size syntax: {value}"
        return float(match.group(1)) * units[match.group(2).upper()]

    assert duration_seconds(flags["storage.tsdb.retention.time"]) == duration_seconds(prom_retention_time), \
        f"Prometheus effective time retention differs from configured policy"
    assert size_bytes(flags["storage.tsdb.retention.size"]) == size_bytes(prom_retention_size), \
        f"Prometheus effective size retention differs from configured policy"
    with urllib.request.urlopen(f"{loki}/config", timeout=10) as response:
        loki_config = response.read().decode()
    retention_values = re.findall(r"(?m)^\s*retention_period:\s*(\S+)\s*$", loki_config)
    lookback_values = re.findall(r"(?m)^\s*max_query_lookback:\s*(\S+)\s*$", loki_config)
    expected_loki_seconds = duration_seconds(loki_retention_period)
    assert any(duration_seconds(value) == expected_loki_seconds for value in retention_values)
    assert any(duration_seconds(value) == expected_loki_seconds for value in lookback_values)
    assert re.search(r"(?m)^\s*retention_enabled:\s*true\s*$", loki_config)
    assert re.search(r"(?m)^\s*delete_request_store:\s*filesystem\s*$", loki_config)
    return {"prometheus_time": prom_retention_time, "prometheus_size": prom_retention_size,
            "loki_time": loki_retention_period, "loki_compactor": True}


def compose_action(*args):
    return subprocess.run(["docker", "compose", *args], check=True, cwd=os.path.dirname(os.path.dirname(__file__)),
                          capture_output=True, text=True)


def exporter_request_counters():
    root = os.path.dirname(os.path.dirname(__file__))
    response = subprocess.run(["docker", "compose", "exec", "-T", "prometheus", "wget", "-qO-",
                               "http://nginxlog-exporter:4040/metrics"], cwd=root,
                              check=True, capture_output=True, text=True).stdout
    values = {app: 0.0 for app in ("app-a", "app-b", "app-c")}
    for line in response.splitlines():
        if not line.startswith("nginx_http_response_count_total{"):
            continue
        labels = dict(re.findall(r'([a-zA-Z_]+)="([^"]*)"', line))
        if labels.get("app") in values and labels.get("method") == "GET" and labels.get("status") == "200":
            values[labels["app"]] = float(line.rsplit(" ", 1)[1])
    return values


def loki_safe_event_count(app, start_ns, path=None, method="GET", status="200"):
    route = path or f"/{app}/"
    expression = f'{{job="nginx",app="{app}"}} | method="{method}" | status="{status}" | path="{route}"'
    # Nginx time_iso8601 is second-granularity; include the preceding seconds
    # to avoid excluding events written in the same second as the batch start.
    return sum(len(stream.get("values", [])) for stream in loki_query(
        expression, start_ns=start_ns - 5_000_000_000, limit=500))


def verify_rotation_and_recovery():
    root = os.path.dirname(os.path.dirname(__file__))
    was_generator_running = bool(compose_action("ps", "--status", "running", "--quiet", "traffic-generator").stdout.strip())
    compose_action("stop", "traffic-generator")
    marker_start = time.time_ns()
    marker_counts = {app: 0 for app in ("app-a", "app-b", "app-c")}
    try:
        time.sleep(7)
        marker_start = time.time_ns()
        metric_before = {app: prom_scalar(f'sum(nginx_http_response_count_total{{app="{app}"}})')
                         for app in marker_counts}

        def emit_markers(prefix, rounds=1):
            for round_number in range(rounds):
                for app in marker_counts:
                    # A request identifier must not be persisted in the access
                    # log. Correlate this isolated batch by its safe route and
                    # exact per-app event count instead.
                    assert request_status(f"{base}/{app}/") == 200
                    marker_counts[app] += 1
                if prefix == "rotate":
                    rotated = subprocess.run([sys.executable, os.path.join(root, "scripts", "rotate_logs.py"),
                                              "--max-bytes", "1", "--keep", "20"],
                                             cwd=root, check=True, capture_output=True, text=True)
                    assert "rotated:6" in rotated.stdout, f"Expected six Nginx files rotated: {rotated.stdout}"

        def assert_safe_batch(expected_counts, phase):
            wait_for(lambda: all(loki_safe_event_count(app, marker_start) >= expected_counts[app]
                                 for app in marker_counts),
                     f"Loki did not ingest the safe-route batch after {phase}", timeout=90)
            observed = {app: loki_safe_event_count(app, marker_start) for app in marker_counts}
            assert observed == expected_counts, \
                f"Loki safe-route events after {phase} were missing or duplicated: expected={expected_counts}, observed={observed}"

        emit_markers("rotate", rounds=2)
        assert_safe_batch(marker_counts.copy(), "log rotation")

        compose_action("stop", "loki")
        emit_markers("loki-down")
        time.sleep(3)
        compose_action("start", "loki")
        wait_for(lambda: request_status(f"{loki}/ready") == 200, "Loki did not recover", timeout=90)
        loki_recovered_counts = {app: marker_counts[app] for app in marker_counts}
        assert_safe_batch(loki_recovered_counts, "Loki restart")

        compose_action("stop", "alloy")
        emit_markers("alloy-down")
        compose_action("start", "alloy")
        assert_safe_batch(marker_counts.copy(), "Alloy restart")

        compose_action("stop", "prometheus")
        emit_markers("prometheus-down")
        time.sleep(7)
        prometheus_started_at = time.time()
        compose_action("start", "prometheus")
        wait_for(lambda: target_scraped_after("nginx-access", prometheus_started_at),
                 "Prometheus target did not recover", timeout=90)
        wait_for(lambda: all(prom_scalar(f'sum(nginx_http_response_count_total{{app="{app}"}})')
                             >= metric_before[app] + marker_counts[app] for app in marker_counts),
                 "Prometheus did not catch up on exporter counters after its interruption", timeout=90)
        metrics_before_exporter_restart = {
            app: round(prom_scalar(f'sum(nginx_http_response_count_total{{app="{app}"}})') - metric_before[app], 1)
            for app in marker_counts}
        assert all(metrics_before_exporter_restart[app] >= marker_counts[app] for app in marker_counts), \
            f"Rotation/recovery counters lost requests before exporter restart: {metrics_before_exporter_restart}"

        compose_action("stop", "nginxlog-exporter")
        emit_markers("exporter-down")
        exporter_started_at = time.time()
        compose_action("start", "nginxlog-exporter")
        wait_for(lambda: target_scraped_after("nginx-access", exporter_started_at) and
                 bool(prom_query("nginx_http_response_count_total")),
                 "Exporter metrics did not recover", timeout=90)
        exporter_recovered = exporter_request_counters()
        assert not any(exporter_recovered.values()), \
            "Exporter restart unexpectedly replayed lines appended during its outage"
        post_restart_at = time.time()
        emit_markers("post-exporter-restart", rounds=1)
        wait_for(lambda: all(exporter_request_counters()[app] >= exporter_recovered[app] + 1
                             for app in marker_counts),
                 "Exporter counters did not advance after post-restart requests", timeout=90)
        wait_for(lambda: target_scraped_after("nginx-access", post_restart_at),
                 "Prometheus did not scrape the recovered exporter", timeout=90)
        assert_safe_batch(marker_counts.copy(), "full pipeline recovery")
        deltas = {}
        exporter_after = exporter_request_counters()
        for app, before in exporter_recovered.items():
            after = exporter_after[app]
            deltas[app] = round(after - before, 1)
            assert deltas[app] >= 1, f"Exporter counters did not advance after restart for {app}: {deltas[app]}"
        return {"isolated_loki_events": sum(marker_counts.values()), "events_per_app": marker_counts,
                "prometheus_counter_deltas_before_exporter_restart": metrics_before_exporter_restart,
                "exporter_outage_events_backfilled": False,
                "post_exporter_restart_deltas": deltas, "rotation_cycles": 2,
                "loki_alloy_prometheus_exporter_recovered": True}
    finally:
        if was_generator_running:
            compose_action("start", "traffic-generator")


def verify_dashboard_and_datasources():
    sources = get_json(f"{grafana}/api/datasources")
    assert {source["name"] for source in sources} >= {"Prometheus", "Loki"}, sources
    expected = {
        "nginx-overview": ("Nginx | Overview", 10),
        "nginx-application-detail": ("Nginx | Application Detail", 10),
        "nginx-live-logs": ("Nginx | Live Logs", 2),
        "nginx-security": ("Nginx | Security", 15),
    }
    dashboards = {}
    counts = {}
    for uid, (title, minimum_panels) in expected.items():
        payload = get_json(f"{grafana}/api/dashboards/uid/{uid}")
        dashboard = payload["dashboard"]
        assert payload["meta"].get("provisioned"), f"{uid} is not provisioned"
        assert dashboard["title"] == title, dashboard["title"]
        panels = dashboard["panels"]
        assert len(panels) >= minimum_panels, f"{uid}: expected >= {minimum_panels} panels, got {len(panels)}"
        if uid == "nginx-overview":
            by_title = {panel["title"]: panel for panel in panels}
            for title in ("Requests by application (period total)", "Applications with the most errors (period total)"):
                bar = by_title[title]
                assert bar.get("type") == "barchart", f"{title} is not a bar chart"
                assert bar.get("options", {}).get("xField") == "Metric", f"{title} does not use series Metric as category"
                assert any(item.get("id") == "seriesToRows"
                           for item in bar.get("transformations", [])), f"{title} does not extract app labels into fields"
                assert " by (app) " in bar["targets"][0]["expr"], f"{title} query does not group by app"
                assert "increase(" in bar["targets"][0]["expr"], f"{title} no longer uses the counter increase estimate"
                assert bar["fieldConfig"]["defaults"].get("decimals") == 0, f"{title} should display whole estimated requests"
                assert "extrapolates" in bar.get("description", ""), f"{title} does not document increase() semantics"
            assert not any("429" in panel["title"] for panel in panels), "Overview reserves space for the synthetic zero-only 429 metric"
            assert any("period total" in panel["title"] for panel in panels if panel.get("type") == "barchart")
            for title in ("Requests in selected period", "4xx responses (period)", "5xx responses (period)"):
                total = by_title[title]
                assert "increase(" in total["targets"][0]["expr"] and "round(" not in total["targets"][0]["expr"]
                assert total["fieldConfig"]["defaults"].get("decimals") == 0
                assert "extrapolates" in total.get("description", "")
        if uid != "nginx-overview":
            variables = dashboard.get("templating", {}).get("list", [])
            assert any(variable.get("name") == "app" for variable in variables), f"{uid} has no app selector"
        if uid == "nginx-application-detail":
            assert any(panel.get("type") == "table" for panel in panels), f"{uid} has no structured request table"
        if uid == "nginx-live-logs":
            live_panel = next(panel for panel in panels if panel["title"] == "HTTP access events")
            assert live_panel.get("type") == "table", f"{uid} access events are not a table"
            assert any("/explore?panes=" in link.get("url", "") for link in dashboard.get("links", [])), "Live Logs has no Explore link"
        if uid == "nginx-security":
            verify_security_dashboard(dashboard)
        dashboards[uid] = dashboard
        counts[uid] = len(panels)
    return sorted(source["name"] for source in sources), counts, dashboards


def grafana_query_expression(expr):
    replacements = {
        "$__rate_interval": "1m", "$__range": "15m", "$__auto": "1m",
        "${method:regex}": ".*", "${path:regex}": ".*",
        "${source_ip:raw}": ".*", "${status:raw}": ".*", "$app": ".*",
    }
    for token, value in replacements.items():
        expr = expr.replace(token, value)
    return expr


def resolve_live_logs_expression(expression, app=".*", method=".*", status=".*", path=".*", source_ip=".*"):
    replacements = {"$app": app, "${method:regex}": method, "${status:raw}": status,
                    "${path:regex}": re.escape(path) if path != ".*" else ".*",
                    "${source_ip:raw}": source_ip}
    for token, value in replacements.items():
        expression = expression.replace(token, value)
    return expression


def verify_live_logs(dashboard):
    panels = {panel["title"]: panel for panel in dashboard["panels"]}
    panel = panels["HTTP access events"]
    target = panel["targets"][0]
    expression = target["expr"]
    assert panel["type"] == "table"
    assert target["queryType"] == "range" and target.get("maxLines") == 500
    expected_columns = {"Time", "app", "method", "status", "path", "Duration (ms)", "remote_addr"}
    transformations = panel.get("transformations", [])
    assert [item["id"] for item in transformations] == ["extractFields", "convertFieldType", "calculateField", "organize"]
    organize = transformations[-1]["options"]
    assert set(organize["indexByName"]) == expected_columns
    assert organize["excludeByName"].get("Line") is True
    assert transformations[0]["options"] == {"source": "Line", "format": "json", "replace": False}
    assert panel["options"]["sortBy"] == [{"displayName": "Time", "desc": True}]
    assert panel["options"]["footer"]["enablePagination"] is True
    status_override = next(item for item in panel["fieldConfig"]["overrides"] if item["matcher"]["options"] == "Status")
    status_properties = {item["id"]: item["value"] for item in status_override["properties"]}
    assert status_properties["thresholds"]["steps"][-2:] == [
        {"color": "orange", "value": 400}, {"color": "red", "value": 500}]
    assert status_properties["custom.cellOptions"]["type"] == "color-background"
    assert panel["gridPos"]["h"] <= 22 and dashboard["panels"][0]["gridPos"]["h"] <= 2

    variables = {item["name"]: item for item in dashboard["templating"]["list"]}
    assert set(variables) >= {"app", "method", "status", "path", "source_ip"}
    assert "only to the access events query" in variables["path"]["description"]
    assert "regular expression" in variables["source_ip"]["description"]
    for name in ("app", "method", "status", "path", "source_ip"):
        assert f"${name}" in expression or f"${{{name}:" in expression, f"Live Logs query omits ${name}"

    links = [item for item in dashboard["links"] if "/explore?panes=" in item.get("url", "")]
    assert len(links) == 1
    link = links[0]
    query_string = urllib.parse.urlsplit(link["url"]).query
    encoded_panes = urllib.parse.parse_qs(query_string)["panes"][0]
    pane = json.loads(encoded_panes)["0"]
    explore_expr = pane["queries"][0]["expr"]
    for token in ('$app', '${method:regex}', '${status:raw}', '${path:regex}', '${source_ip:raw}'):
        assert token in explore_expr, f"Explore link omits current filter {token}"
    assert pane["range"] == {"from": "$__from", "to": "$__to"}
    assert "Open Explore with current application" in link.get("tooltip", "")

    # Produce a deterministic local event to exercise each filter and their combination.
    status_code = request_status(f"{base}/app-a/forbidden")
    assert status_code == 403, f"Expected controlled 403 event, got {status_code}"
    # A dotted path exercises Grafana's regex escaping (\.) inside the LogQL path filter.
    dotted_status = request_status(f"{base}/app-a/.env")
    assert dotted_status == 404, f"Expected controlled dotted-path 404 event, got {dotted_status}"
    wait_for(lambda: bool(loki_query('{job="nginx",app="app-a"} | path=~`.*[.]env.*`')),
             "Synthetic dotted-path request was not ingested by Loki")
    wait_for(lambda: bool(loki_query('{job="nginx",app="app-a"} | method="GET" | status="403" | path=~".*forbidden.*"')),
             "Synthetic 403 request was not ingested by Loki")
    raw_streams = loki_query('{job="nginx",app="app-a"} | method="GET" | status="403" | path=~".*forbidden.*"')
    controlled = [json.loads(line) for stream in raw_streams for _, line in stream["values"]]
    event = next(item for item in controlled if item.get("path", "").endswith("/forbidden"))
    # RE2 character classes avoid LogQL's Go-string escape rules for literal dots.
    source_ip_regex = event["remote_addr"].replace(".", "[.]")

    filters = {
        "Application": (resolve_live_logs_expression(expression, app="app-a"), lambda e: e["app"] == "app-a"),
        "Method": (resolve_live_logs_expression(expression, method="GET"), lambda e: e["method"] == "GET"),
        "Status": (resolve_live_logs_expression(expression, status="4.."), lambda e: str(e["status"]).startswith("4")),
        "Path": (resolve_live_logs_expression(expression, path="forbidden"), lambda e: "forbidden" in e["path"]),
        "Path with dot": (resolve_live_logs_expression(expression, path=".env"), lambda e: ".env" in e["path"]),
        "Source IP": (resolve_live_logs_expression(expression, source_ip=source_ip_regex), lambda e: re.fullmatch(source_ip_regex, e["remote_addr"]) is not None),
        "Combined": (resolve_live_logs_expression(expression, app="app-a", method="GET", status="403",
                                                    path="forbidden", source_ip=source_ip_regex),
                     lambda e: e["app"] == "app-a" and e["method"] == "GET" and e["status"] == 403
                     and e["path"].endswith("/forbidden") and e["remote_addr"] == event["remote_addr"]),
    }
    filter_counts = {}
    for label, (query, predicate) in filters.items():
        streams = loki_query(query)
        events = [json.loads(line) for stream in streams for _, line in stream["values"]]
        assert events and all(predicate(item) for item in events), f"{label} filter returned empty or mismatched events: {events[:3]}"
        filter_counts[label] = len(events)
    app_b_streams = loki_query(resolve_live_logs_expression(expression, app="app-b"))
    app_b_events = [json.loads(line) for stream in app_b_streams for _, line in stream["values"]]
    assert app_b_events and all(item["app"] == "app-b" for item in app_b_events), "Application selector leaked across apps"

    # Grafana's data source API confirms the raw line is still present for row details/Explore.
    grafana_frames = grafana_loki_frames(resolve_live_logs_expression(expression, app="app-a"), max_lines=500)
    assert grafana_frames, "Grafana Loki range query returned no recent events"
    fields = {field["name"] for frame in grafana_frames for field in frame["schema"]["fields"]}
    assert {"Line", "Time"} <= fields, f"Grafana frames lost the original event line: {fields}"
    visible_events = [len(frame.get("data", {}).get("values", [[]])[0]) for frame in grafana_frames]
    assert sum(visible_events) <= 500, f"Grafana query exceeded configured 500 row limit: {visible_events}"

    return {"filters": filter_counts, "grafana_frames": len(grafana_frames), "events": sum(visible_events),
            "max_lines": target["maxLines"], "explore_filters": 5}


def verify_grafana_live_websocket():
    endpoint = urllib.parse.urlsplit(grafana)
    port = endpoint.port or (443 if endpoint.scheme == "https" else 80)
    key = base64.b64encode(os.urandom(16)).decode()
    origin = f"{endpoint.scheme}://{endpoint.netloc}"
    authorization = base64.b64encode(f"{grafana_user}:{grafana_password}".encode()).decode()
    request = (f"GET /api/live/ws HTTP/1.1\r\nHost: {endpoint.netloc}\r\n"
               f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
               f"Sec-WebSocket-Version: 13\r\nOrigin: {origin}\r\n"
               f"Authorization: Basic {authorization}\r\n\r\n").encode()
    with socket.create_connection((endpoint.hostname, port), timeout=5) as connection:
        connection.settimeout(5)
        connection.sendall(request)
        response = b""
        while b"\r\n\r\n" not in response and len(response) < 16384:
            chunk = connection.recv(4096)
            if not chunk:
                break
            response += chunk
    headers = response.decode("latin-1", errors="replace")
    status_line = headers.split("\r\n", 1)[0]
    assert " 101 " in status_line, f"Grafana Live websocket upgrade failed: {status_line}"
    expected_accept = base64.b64encode(hashlib.sha1(
        (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
    assert f"Sec-WebSocket-Accept: {expected_accept}" in headers, "Grafana returned an invalid WebSocket accept key"
    return status_line


def resolve_security_expression(expression, app=".*", source_ip=".*"):
    return expression.replace('$app', app).replace('${source_ip:raw}', source_ip)


def verify_security_dashboard(dashboard):
    panels = {panel["title"]: panel for panel in dashboard["panels"]}
    rows = [panel["title"] for panel in dashboard["panels"] if panel.get("type") == "row"]
    assert rows == ["Overview", "Suspicious Activity", "Investigation"], rows
    assert [panels[title]["gridPos"]["y"] for title in rows] == [0, 14, 32]

    methods = panels["HTTP methods (estimated period total)"]
    method_expr = methods["targets"][0]["expr"]
    assert "increase(" in method_expr and methods["fieldConfig"]["defaults"].get("decimals") == 0
    assert methods["options"].get("xField") == "Metric"
    assert [item.get("id") for item in methods.get("transformations", [])] == ["seriesToRows"]
    assert "extrapolates" in methods["description"] and "rounded" in methods["description"]
    frames = grafana_prom_frames(grafana_query_expression(method_expr), methods["targets"][0]["legendFormat"])
    labels = {field.get("labels", {}).get("method") for frame in frames
              for field in frame["schema"]["fields"] if field["name"] == "Value"}
    assert labels >= {"GET", "POST"}, f"HTTP methods lost their method series: {labels}"

    rate_panels = [panel for panel in dashboard["panels"]
                   if panel.get("type") in ("stat", "timeseries")
                   and panel.get("fieldConfig", {}).get("defaults", {}).get("unit") == "reqps"]
    assert rate_panels, "No HTTP rate panels found"
    for panel in rate_panels:
        defaults = panel["fieldConfig"]["defaults"]
        assert "min" not in defaults and "max" not in defaults, f"{panel['title']} has a fixed scale"
        assert defaults.get("decimals", 0) >= 3, f"{panel['title']} does not retain precision below 1 req/s"
    for panel in rate_panels:
        assert "rate(" in panel["targets"][0]["expr"], f"{panel['title']} is not a current rate"
    assert "period total" in panels["429 responses (period total, estimated)"]["title"]
    assert "increase(" in panels["429 responses (period total, estimated)"]["targets"][0]["expr"]
    assert "cumulative exporter parse errors" in panels["Exporter parse errors (collection health)"]["description"].lower()
    metric_series = prom_query("nginx_http_response_count_total")
    assert metric_series and all("remote_addr" not in item["metric"] for item in metric_series), \
        "Source IP must not become a Prometheus label"

    scanner = panels["Observed scanner-like paths"]
    scanner_expr = scanner["targets"][0]["expr"]
    assert "$__range" in scanner_expr, "Scanner paths must use the dashboard-selected time range"
    assert 'remote_addr=~"${source_ip:raw}"' in scanner_expr, "Scanner paths must honor the Source IP filter"
    assert scanner["targets"][0].get("queryType") == "instant"
    assert all(path in scanner_expr for path in (".env", ".git", "wp-admin", "wp-login", "phpmyadmin", "/etc/passwd"))
    assert "not proof of an attack" in scanner["description"] and "query errors are reported separately" in scanner["description"]

    origins = panels["Origins with repeated 4xx / 5xx (by app)"]
    origin_expr = origins["targets"][0]["expr"]
    assert "$__range" in origin_expr, "Repeated origins must use the dashboard-selected time range"
    assert "topk(10," in origin_expr and "status=~\"4..|5..\"" in origin_expr
    assert "remote_addr=~\"${source_ip:raw}\"" in origin_expr and "sum by (app,remote_addr)" in origin_expr
    assert " >= 2)" in origin_expr, "Origins panel does not require repeated errors"
    assert "ephemeral query result dimension" in origins["description"]

    recent = panels["Recent security events"]
    assert recent["type"] == "table" and recent["targets"][0]["queryType"] == "range"
    assert recent["targets"][0].get("maxLines") == 500
    assert recent["options"].get("sortBy") == [{"displayName": "Time", "desc": True}]
    assert [item["id"] for item in recent["transformations"]] == [
        "extractFields", "convertFieldType", "calculateField", "organize"]
    organize = recent["transformations"][-1]["options"]
    columns = {"Time", "app", "status", "method", "path", "remote_addr", "Duration (ms)"}
    assert set(organize["indexByName"]) == columns
    hidden_fields = {"Line", "labels", "tsNs", "labelTypes", "id", "time", "request_time", "remote_user",
                     "time_local", "request", "body_bytes_sent", "http_referer", "http_user_agent"}
    assert hidden_fields <= {name for name, excluded in organize["excludeByName"].items() if excluded is True}
    assert "${source_ip:raw}" in recent["targets"][0]["expr"] and '$app' in recent["targets"][0]["expr"]
    assert "403|404|5.." in recent["targets"][0]["expr"]

    explore_links = [link for link in dashboard["links"] if "/explore?panes=" in link.get("url", "")]
    assert len(explore_links) == 1
    panes = json.loads(urllib.parse.parse_qs(urllib.parse.urlsplit(explore_links[0]["url"]).query)["panes"][0])
    explore_expr = panes["0"]["queries"][0]["expr"]
    assert '$app' in explore_expr and '${source_ip:raw}' in explore_expr and "403|404|5.." in explore_expr
    assert panes["0"]["range"] == {"from": "$__from", "to": "$__to"}
    return {"methods": sorted(labels, key=lambda value: "" if value is None else value),
            "sections": rows, "rate_panels": len(rate_panels), "recent_columns": len(columns)}


def verify_security_scenario(dashboard, scan_start_ns):
    panels = {panel["title"]: panel for panel in dashboard["panels"]}
    scanner = panels["Observed scanner-like paths"]
    scan_query = grafana_query_expression(scanner["targets"][0]["expr"])
    path_pattern = re.search(r'path=~"([^"]+)"', scan_query).group(1)
    scan_log_query = '{job="nginx",app=~".*"} | path=~"' + path_pattern + '"'
    eval_end_ns = time.time_ns()
    selected_start_ns = eval_end_ns - 900_000_000_000
    scan_results = loki_query(scan_log_query, start_ns=scan_start_ns, end_ns=eval_end_ns, limit=500)
    scan_events = [json.loads(line) for stream in scan_results for _, line in stream.get("values", [])]
    expected_paths = (".env", ".git/config", "/wp-admin", "/wp-login.php", "/phpmyadmin", "/etc/passwd")
    assert scan_events, "Scan scenario ran, but no matching scanner-like paths were returned"
    assert all(any(event.get("path", "").endswith(path) for path in expected_paths) for event in scan_events), scan_events[:5]
    assert {event.get("app") for event in scan_events} <= {"app-a", "app-b", "app-c"}
    assert all(str(event.get("status", "")).startswith(("4", "5")) for event in scan_events), "Synthetic probe produced no corresponding error responses"
    metric_paths = loki_instant(scan_query, eval_time_ns=eval_end_ns)
    metric_path_counts = {(item["metric"].get("app"), item["metric"].get("path")): float(item["value"][1])
                          for item in metric_paths}
    expected_scan_counts = {}
    for event in scan_events:
        key = (event["app"], event["path"])
        expected_scan_counts[key] = expected_scan_counts.get(key, 0) + 1
    assert metric_paths and all(metric_path_counts.get(key, 0) >= count
                                for key, count in expected_scan_counts.items()), (expected_scan_counts, metric_path_counts)
    app_a_scan = loki_instant(grafana_query_expression(resolve_security_expression(
        scanner["targets"][0]["expr"], app="app-a")), eval_time_ns=eval_end_ns)
    assert app_a_scan and all(item["metric"].get("app") == "app-a" for item in app_a_scan), app_a_scan

    origins_panel = panels["Origins with repeated 4xx / 5xx (by app)"]
    origin_expr = grafana_query_expression(origins_panel["targets"][0]["expr"])
    all_origins = loki_instant(origin_expr, eval_time_ns=eval_end_ns)
    assert all_origins and all(float(result["value"][1]) >= 2 for result in all_origins), all_origins
    scan_ips = {event["remote_addr"] for event in scan_events}
    expected_origin_counts = {}
    for event in scan_events:
        if str(event["status"]).startswith(("4", "5")):
            key = (event["app"], event["remote_addr"])
            expected_origin_counts[key] = expected_origin_counts.get(key, 0) + 1
    actual_origin_counts = {(item["metric"].get("app"), item["metric"].get("remote_addr")): float(item["value"][1])
                            for item in all_origins}
    repeated_expected = {key: count for key, count in expected_origin_counts.items() if count >= 2}
    assert any(key in actual_origin_counts for key in repeated_expected), (repeated_expected, actual_origin_counts)
    assert all(actual_origin_counts[key] >= count for key, count in repeated_expected.items() if key in actual_origin_counts), \
        (repeated_expected, actual_origin_counts)
    matching_origins = [result for result in all_origins if result["metric"].get("remote_addr") in scan_ips]
    assert matching_origins, f"No repeated-error origin correlated with scanner source {scan_ips}: {all_origins}"
    app_a_origins = loki_instant(grafana_query_expression(
        resolve_security_expression(origins_panel["targets"][0]["expr"], app="app-a")),
                                 eval_time_ns=eval_end_ns)
    assert app_a_origins and all(item["metric"].get("app") == "app-a" for item in app_a_origins), app_a_origins
    source_ip_regex = next(iter(scan_ips)).replace(".", "[.]")
    selected_source_ip = next(iter(scan_ips))
    ip_only_scan = loki_instant(grafana_query_expression(resolve_security_expression(
        scanner["targets"][0]["expr"], source_ip=source_ip_regex)), eval_time_ns=eval_end_ns)
    expected_ip_counts = {}
    for event in scan_events:
        if re.fullmatch(source_ip_regex, event["remote_addr"]):
            key = (event["app"], event["path"])
            expected_ip_counts[key] = expected_ip_counts.get(key, 0) + 1
    ip_metric_counts = {(item["metric"].get("app"), item["metric"].get("path")): float(item["value"][1])
                        for item in ip_only_scan}
    assert ip_only_scan and all(ip_metric_counts.get(key, 0) >= count for key, count in expected_ip_counts.items()), \
        (expected_ip_counts, ip_metric_counts)
    combined_scan = loki_instant(grafana_query_expression(resolve_security_expression(
        scanner["targets"][0]["expr"], app="app-a", source_ip=source_ip_regex)), eval_time_ns=eval_end_ns)
    assert combined_scan and all(item["metric"].get("app") == "app-a" for item in combined_scan), combined_scan
    ip_only_origins = loki_instant(grafana_query_expression(resolve_security_expression(
        origins_panel["targets"][0]["expr"], source_ip=source_ip_regex)), eval_time_ns=eval_end_ns)
    assert ip_only_origins and all(item["metric"].get("remote_addr") in scan_ips for item in ip_only_origins), ip_only_origins
    combined_origins = loki_instant(grafana_query_expression(resolve_security_expression(
        origins_panel["targets"][0]["expr"], app="app-a", source_ip=source_ip_regex)), eval_time_ns=eval_end_ns)
    assert combined_origins and all(item["metric"].get("app") == "app-a" and
                                    item["metric"].get("remote_addr") == selected_source_ip and
                                    float(item["value"][1]) >= 2 for item in combined_origins), combined_origins

    recent_panel = panels["Recent security events"]
    recent_all_expr = resolve_security_expression(recent_panel["targets"][0]["expr"])
    recent_all_streams = loki_query(recent_all_expr, start_ns=selected_start_ns, end_ns=eval_end_ns, limit=500)
    recent_all_events = [json.loads(line) for stream in recent_all_streams for _, line in stream.get("values", [])]
    assert recent_all_events and len(recent_all_events) <= 500
    assert all(event.get("app") in {"app-a", "app-b", "app-c"} and
               str(event.get("status", "")).startswith(("4", "5")) for event in recent_all_events)
    assert {event["path"] for event in scan_events} <= {event["path"] for event in recent_all_events}
    recent_app_expr = resolve_security_expression(recent_panel["targets"][0]["expr"], app="app-a")
    recent_app_streams = loki_query(recent_app_expr, start_ns=selected_start_ns, end_ns=eval_end_ns, limit=500)
    recent_app_events = [json.loads(line) for stream in recent_app_streams for _, line in stream.get("values", [])]
    assert recent_app_events and all(event.get("app") == "app-a" for event in recent_app_events)
    recent_ip_expr = resolve_security_expression(recent_panel["targets"][0]["expr"], source_ip=source_ip_regex)
    recent_ip_streams = loki_query(recent_ip_expr, start_ns=selected_start_ns, end_ns=eval_end_ns, limit=500)
    recent_ip_events = [json.loads(line) for stream in recent_ip_streams for _, line in stream.get("values", [])]
    assert recent_ip_events and all(event.get("remote_addr") in scan_ips for event in recent_ip_events)
    recent_expr = resolve_security_expression(recent_panel["targets"][0]["expr"], app="app-a", source_ip=source_ip_regex)
    recent_streams = loki_query(recent_expr, start_ns=selected_start_ns, end_ns=eval_end_ns, limit=500)
    recent_events = [json.loads(line) for stream in recent_streams for _, line in stream.get("values", [])]
    assert recent_events and len(recent_events) <= 500 and all(event.get("app") == "app-a" and
                                 event.get("remote_addr") in scan_ips and
                                 str(event.get("status", "")).startswith(("4", "5")) for event in recent_events), recent_events[:5]
    recent_scan_paths = {event["path"] for event in recent_events}
    app_a_scan_paths = {event["path"] for event in scan_events if event["app"] == "app-a"}
    assert app_a_scan_paths <= recent_scan_paths, (app_a_scan_paths, recent_scan_paths)
    frames = grafana_loki_frames(recent_expr, max_lines=500)
    fields = {field["name"] for frame in frames for field in frame["schema"]["fields"]}
    assert {"Line", "Time"} <= fields, f"Recent security events lost the original JSON: {fields}"
    return {"scan_events": len(scan_events), "scan_apps": sorted({event["app"] for event in scan_events}),
            "origins": len(all_origins), "correlated_ips": sorted(scan_ips), "ip_filter_origins": len(ip_only_origins),
            "app_ip_combined_origins": len(combined_origins), "scanner_app_filter_series": len(app_a_scan),
            "scanner_ip_filter_series": len(ip_only_scan), "scanner_combined_series": len(combined_scan),
            "recent_all_events": len(recent_all_events), "recent_app_filter_events": len(recent_app_events),
            "recent_ip_filter_events": len(recent_ip_events), "recent_app_a_events": len(recent_events)}


def verify_dashboard_queries(dashboards):
    checked = {"prometheus": 0, "loki": 0}
    for dashboard in dashboards.values():
        for panel in dashboard["panels"]:
            for target in panel.get("targets", []):
                expr = grafana_query_expression(target["expr"])
                ds_type = target.get("datasource", {}).get("type")
                if ds_type == "prometheus":
                    series = prom_query(expr)
                    if dashboard["uid"] == "nginx-overview" and panel["title"] in (
                        "Requests by application (period total)",
                        "Applications with the most errors (period total)",
                    ):
                        apps = {item["metric"].get("app") for item in series}
                        assert apps == {"app-a", "app-b", "app-c"}, (panel["title"], apps, series)
                    checked["prometheus"] += 1
                elif ds_type == "loki":
                    is_metric = bool(re.search(r"\]\s*\)\s*$", expr)) or "topk(" in expr or "max_over_time(" in expr
                    params = {"query": expr, "limit": "50"}
                    if is_metric:
                        url = f"{loki}/loki/api/v1/query?{urllib.parse.urlencode(params)}"
                    else:
                        end = time.time_ns()
                        params.update({"start": str(end - 900_000_000_000), "end": str(end)})
                        url = f"{loki}/loki/api/v1/query_range?{urllib.parse.urlencode(params)}"
                    result = get_json(url)
                    assert result.get("status") == "success", (panel["title"], expr, result)
                    checked["loki"] += 1
    return checked


def verify_overview_bar_categories(dashboard):
    expected = {"app-a", "app-b", "app-c"}
    titles = ("Requests by application (period total)", "Applications with the most errors (period total)")
    for title in titles:
        panel = next(item for item in dashboard["panels"] if item["title"] == title)
        expression = grafana_query_expression(panel["targets"][0]["expr"])
        frames = grafana_prom_frames(expression)
        labels = set()
        series_names = set()
        for frame in frames:
            fields = frame["schema"]["fields"]
            value_field = next(field for field in fields if field["name"] == "Value")
            if "app" in value_field.get("labels", {}):
                labels.add(value_field["labels"]["app"])
                series_names.add(value_field.get("config", {}).get("displayNameFromDS"))
        assert labels == expected, f"{title}: Grafana query frame labels do not identify every app: {labels}"
        assert series_names == expected, f"{title}: Grafana series names are not one name per app: {series_names}"
        selected = grafana_prom_frames(expression.replace('app=~".*"', 'app=~"app-b"'))
        selected_apps = {
            field.get("labels", {}).get("app")
            for frame in selected for field in frame["schema"]["fields"] if field["name"] == "Value"
        }
        assert selected_apps == {"app-b"}, f"{title}: app variable filter leaked: {selected_apps}"
    return len(titles) * 2


def verify_application_detail(dashboard):
    panels = {panel["title"]: panel for panel in dashboard["panels"]}
    methods = panels["Methods (estimated period total)"]
    assert methods.get("type") == "barchart"
    method_target = methods["targets"][0]
    assert "increase(" in method_target["expr"] and "round(" not in method_target["expr"]
    assert methods["fieldConfig"]["defaults"].get("decimals") == 0
    assert "extrapolates" in methods.get("description", "") and "not an exact" in methods.get("description", "")
    assert methods.get("options", {}).get("xField") == "Metric", "Methods category must be the method series name"
    assert any(item.get("id") == "seriesToRows" for item in methods.get("transformations", [])), "Methods must expose GET/POST as category rows"
    assert method_target.get("legendFormat") == "{{method}}"
    method_frames = grafana_prom_frames(grafana_query_expression(method_target["expr"]), method_target["legendFormat"])
    method_labels = {field.get("labels", {}).get("method") for frame in method_frames
                     for field in frame["schema"]["fields"] if field["name"] == "Value"}
    assert method_labels >= {"GET", "POST"}, f"Methods query lost its HTTP method categories: {method_labels}"

    paths = panels["Most requested paths (event count)"]
    assert "sum by (path)" in paths["targets"][0]["expr"], "Path bars must aggregate by readable path without repeating app labels"
    assert "topk(10," in paths["targets"][0]["expr"]
    assert paths["fieldConfig"]["defaults"].get("decimals") == 0
    assert "Exact Loki event count" in paths.get("description", "")
    assert paths.get("options", {}).get("xField") == "Metric", "Path category must use the path series name"
    path_transform_ids = [item.get("id") for item in paths.get("transformations", [])]
    assert path_transform_ids == ["seriesToRows", "sortBy"], f"Path bars must sort the transformed values: {path_transform_ids}"
    sort_options = paths["transformations"][1]["options"]["sort"][0]
    assert sort_options == {"field": "Value", "desc": True}, sort_options
    assert paths["targets"][0].get("legendFormat") == "{{path}}"
    path_expr = grafana_query_expression(paths["targets"][0]["expr"])
    path_results = loki_instant(path_expr)
    path_values = [float(item["value"][1]) for item in path_results]
    assert path_results and len(path_results) <= 10 and all(item["metric"].get("path") for item in path_results), "Loki path query returned no readable path labels"
    path_sort = paths["transformations"][1]["options"]["sort"][0]
    assert path_sort == {"field": "Value", "desc": True}, "Grafana must sort the top paths by volume descending"
    app_a_paths = loki_instant(path_expr.replace('app=~".*"', 'app=~"app-a"'))
    app_a_path_labels = {item["metric"].get("path", "") for item in app_a_paths}
    assert app_a_paths and any(path.startswith("/app-a/") for path in app_a_path_labels) \
        and all(path.startswith("/app-a/") or path == "/_unclassified" for path in app_a_path_labels), (path_expr, app_a_paths)
    path_frames = grafana_loki_frames(path_expr, query_type="instant", legend_format=paths["targets"][0]["legendFormat"])
    path_names = {field.get("config", {}).get("displayNameFromDS") for frame in path_frames
                  for field in frame["schema"]["fields"] if field["name"] == "Value"}
    assert path_names and all(name.startswith("/") for name in path_names), f"Loki path categories are not readable: {path_names}"

    for title in ("P50 latency", "P95 latency", "P99 latency"):
        percentile = panels[title]
        target = percentile["targets"][0]
        assert "sum by (le,app)" in target["expr"], f"{title} must preserve application series"
        assert target.get("legendFormat") == "{{app}}", f"{title} must label values by app"
        assert target.get("instant") is True, f"{title} must show one current value per app"
        assert percentile["options"].get("textMode") == "value_and_name", f"{title} should show each app name beside the value"
        assert percentile["options"].get("orientation") == "horizontal", f"{title} should align the single-app name and value horizontally"
        frames = grafana_prom_frames(grafana_query_expression(target["expr"]), target["legendFormat"])
        app_labels = {field.get("labels", {}).get("app") for frame in frames
                      for field in frame["schema"]["fields"] if field["name"] == "Value"}
        assert app_labels >= {"app-a", "app-b", "app-c"}, f"{title} has unlabeled/missing apps: {app_labels}"
        display_names = {field.get("config", {}).get("displayNameFromDS") for frame in frames
                         for field in frame["schema"]["fields"] if field["name"] == "Value"}
        assert display_names >= {"app-a", "app-b", "app-c"}, f"{title} Grafana series names do not identify each app: {display_names}"
        selected = grafana_prom_frames(grafana_query_expression(target["expr"]).replace(
            'app=~".*"', 'app=~"app-a"').replace('method=~".*"', 'method=~"GET"').replace(
                'status=~".*"', 'status=~"2.."'), target["legendFormat"])
        selected_apps = {field.get("labels", {}).get("app") for frame in selected
                         for field in frame["schema"]["fields"] if field["name"] == "Value"}
        assert selected_apps == {"app-a"} and len(selected) == 1, f"{title} single-app selection leaked or returned multiple series: {selected_apps}"

    selected_method = grafana_prom_frames(grafana_query_expression(method_target["expr"]).replace(
        'app=~".*"', 'app=~"app-a"').replace('method=~".*"', 'method=~"GET"').replace(
            'status=~".*"', 'status=~"2.."'), method_target["legendFormat"])
    selected_method_labels = {field.get("labels", {}).get("method") for frame in selected_method
                              for field in frame["schema"]["fields"] if field["name"] == "Value"}
    assert selected_method_labels == {"GET"}, f"Prometheus method/status filters did not constrain Methods: {selected_method_labels}"

    slow = panels["Slowest by app/method/status/path"]
    slow_expr = grafana_query_expression(slow["targets"][0]["expr"])
    assert slow["targets"][0].get("queryType") == "instant"
    assert "topk(10," in slow["targets"][0]["expr"] and "1000 *" in slow["targets"][0]["expr"]
    assert slow["fieldConfig"]["defaults"].get("unit") == "ms" and slow["fieldConfig"]["defaults"].get("decimals") == 0
    assert "top 10" in slow.get("description", "") and "descending" in slow.get("description", "")
    slow_transform_ids = [item.get("id") for item in slow.get("transformations", [])]
    assert slow_transform_ids == ["seriesToRows", "sortBy", "organize"], slow_transform_ids
    assert slow["transformations"][1]["options"]["sort"] == [{"field": "Value", "desc": True}]
    assert slow["transformations"][2]["options"]["renameByName"].get("Value") == "Max duration (ms)"
    assert "$__range" in slow["targets"][0]["expr"], "Slow request lookup should use the selected dashboard range"
    try:
        with urllib.request.urlopen(f"{base}/app-a/slower", timeout=4) as response:
            assert response.status == 200
    except urllib.error.HTTPError as error:
        assert error.code == 200

    def slow_event_arrived():
        streams = loki_query('{job="nginx",app="app-a"}')
        for stream in streams:
            for _, line in stream["values"]:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("path", "").endswith("/slower") and float(event.get("request_time", 0)) >= 0.7:
                    return True
        return False

    wait_for(slow_event_arrived, "Controlled /slower request was not ingested by Loki")
    slow_results = loki_instant(slow_expr)
    slow_values = [float(item["value"][1]) for item in slow_results]
    assert len(slow_results) <= 10 and slow["transformations"][1]["options"]["sort"] == [{"field": "Value", "desc": True}], slow_values
    slow_app_a = [item for item in slow_results if item["metric"].get("app") == "app-a"]
    assert slow_app_a and max(float(item["value"][1]) for item in slow_app_a) >= 700, slow_results
    slow_frames = grafana_loki_frames(slow_expr, query_type="instant", legend_format=slow["targets"][0]["legendFormat"])
    slow_frame_labels = {label for frame in slow_frames for field in frame["schema"]["fields"]
                         for label in field.get("labels", {})}
    assert {"app", "method", "status", "path"} <= slow_frame_labels, f"Slow request query lacks structured identifiers: {slow_frame_labels}"
    assert "remote_addr" not in slow_frame_labels, f"Slow request grouping should not split by source IP: {slow_frame_labels}"
    slow_names = {field.get("config", {}).get("displayNameFromDS", "") for frame in slow_frames
                  for field in frame["schema"]["fields"] if field["name"] == "Value"}
    assert any(all(part in name for part in ("app-a", "GET", "/app-a/slower")) for name in slow_names), slow_names
    filtered_slow_expr = (slow_expr.replace('app=~".*"', 'app=~"app-a"')
                          .replace('method=~".*"', 'method=~"GET"').replace('status=~".*"', 'status=~"2.."')
                          .replace('path=~`.*.*.*`', 'path=~`.*slower.*`'))
    filtered_slow = loki_instant(filtered_slow_expr)
    assert filtered_slow and all(item["metric"].get("app") == "app-a" and
                                 item["metric"].get("method") == "GET" and
                                 item["metric"].get("status", "").startswith("2") and
                                 item["metric"].get("path", "").endswith("/slower") and
                                 float(item["value"][1]) >= 700 for item in filtered_slow), filtered_slow
    slow_app_b = loki_instant(slow_expr.replace('app=~".*"', 'app=~"app-b"'))
    assert all(item["metric"].get("app") == "app-b" for item in slow_app_b), slow_app_b

    recent = panels["Recent requests for selected app"]
    assert recent.get("type") == "table", "Recent requests should be a structured table"
    assert recent["targets"][0].get("queryType") == "range"
    transform_ids = [item.get("id") for item in recent.get("transformations", [])]
    assert transform_ids == ["extractFields", "convertFieldType", "calculateField", "organize"], transform_ids
    extract = next((item for item in recent.get("transformations", []) if item.get("id") == "extractFields"), None)
    assert extract and extract.get("options", {}).get("source") == "Line", "Recent request table must parse fields from the raw event line"
    conversion = recent["transformations"][1]["options"]["conversions"]
    assert conversion == [{"targetField": "request_time", "destinationType": "number"}], conversion
    calculation = recent["transformations"][2]["options"]
    assert calculation["mode"] == "binary" and calculation["binary"]["operator"] == "*"
    assert calculation["binary"]["right"] == {"fixed": "1000"} and calculation["alias"] == "Duration (ms)"
    organize = next((item for item in recent.get("transformations", []) if item.get("id") == "organize"), None)
    assert organize, "Recent request table must organize the seven requested columns"
    expected_columns = {"Time", "app", "method", "status", "path", "Duration (ms)", "remote_addr"}
    assert set(organize["options"]["indexByName"]) == expected_columns
    assert organize["options"]["excludeByName"].get("Line") is True, "Raw JSON should not be a visible table column"
    duration_override = next(item for item in recent["fieldConfig"]["overrides"] if item["matcher"]["options"] == "Duration (ms)")
    assert {item["id"]: item["value"] for item in duration_override["properties"]} == {"unit": "ms", "decimals": 0}
    expr = recent["targets"][0]["expr"]
    for selector in ('$app', '${method:regex}', '${status:raw}', '${path:regex}'):
        assert selector in expr, f"Recent requests filter omits {selector}"
    frames = grafana_loki_frames(grafana_query_expression(expr))
    assert frames, "Recent request Loki frame is empty"
    assert {field["name"] for frame in frames for field in frame["schema"]["fields"]} >= {"Line", "Time"}
    raw_index = next(index for index, field in enumerate(frames[0]["schema"]["fields"]) if field["name"] == "Line")
    raw_rows = frames[0]["data"]["values"][raw_index]
    assert raw_rows and {"time", "app", "method", "path", "status", "request_time"} <= set(json.loads(raw_rows[0])), "Raw event column does not preserve the full JSON event"
    # Exercise all four variables together against the known synthetic slow event.
    selected_log_expr = (expr.replace('app=~"$app"', 'app=~"app-a"')
                         .replace('${method:regex}', 'GET').replace('${status:raw}', '2..')
                         .replace('${path:regex}', 'slower'))
    selected_logs = loki_query(selected_log_expr)
    selected_events = [json.loads(line) for stream in selected_logs for _, line in stream["values"]]
    matching = [event for event in selected_events if event.get("path", "").endswith("/slower")]
    assert matching and all(event.get("app") == "app-a" and event.get("method") == "GET"
                            and str(event.get("status", "")).startswith("2") for event in matching), selected_events
    other_app_expr = selected_log_expr.replace('app=~"app-a"', 'app=~"app-b"')
    other_logs = loki_query(other_app_expr)
    other_events = [json.loads(line) for stream in other_logs for _, line in stream["values"]]
    assert all(event.get("app") == "app-b" for event in other_events), other_events
    filtered_paths = (path_expr.replace('app=~".*"', 'app=~"app-a"')
                      .replace('method=~".*"', 'method=~"GET"').replace('status=~".*"', 'status=~"2.."')
                      .replace('path=~`.*.*.*`', 'path=~`.*slower.*`'))
    path_filter_results = loki_instant(filtered_paths)
    assert path_filter_results and all(item["metric"].get("path", "").endswith("/slower") for item in path_filter_results), path_filter_results

    # A path variable is a Loki event-field filter; it is intentionally not a Prometheus label.
    for title in ("Most requested paths (event count)", "Slowest by app/method/status/path", "Recent requests for selected app"):
        target_expr = panels[title]["targets"][0]["expr"]
        for selector in ('$app', '${method:regex}', '${status:raw}', '${path:regex}'):
            assert selector in target_expr, f"{title} filter omits {selector}"
    for title, panel in panels.items():
        if panel.get("targets", [{}])[0].get("datasource", {}).get("type") == "prometheus":
            expression = panel["targets"][0]["expr"]
            assert '$app' in expression, f"{title} is not application scoped"
            assert '${method:regex}' in expression, f"{title} does not honor the method filter"
            assert '${status:raw}' in expression, f"{title} does not honor the status filter"
    return {"method_categories": sorted(method_labels), "path_categories": len(path_results), "paths_descending": path_sort == {"field": "Value", "desc": True},
            "slow_app_a_values": len(slow_app_a), "recent_frames": len(frames)}


def verify_no_traffic_interval():
    time.sleep(12)
    for app in ("app-a", "app-b", "app-c"):
        total = prom_query(f'sum by (app) (increase(nginx_http_response_count_total{{app="{app}"}}[10s]))')
        assert total and len(total) == 1 and total[0]["metric"].get("app") == app, (app, total)
        assert float(total[0]["value"][1]) == 0, f"{app}: request total was nonzero in an idle 10s interval: {total}"
        errors = prom_query(f'sum by (app) (increase(nginx_http_response_count_total{{app="{app}",status=~"4..|5.."}}[10s])) or on (app) (0 * sum by (app) (nginx_http_response_count_total{{app="{app}"}}))')
        assert errors and len(errors) == 1 and errors[0]["metric"].get("app") == app, (app, errors)
        assert float(errors[0]["value"][1]) == 0, f"{app}: error total was nonzero in an idle 10s interval: {errors}"
    return 3


def verify_queries():
    counts = prom_query("nginx_http_response_count_total")
    apps = {series["metric"].get("app") for series in counts}
    assert apps == {"app-a", "app-b", "app-c"}, f"Unexpected/missing app label values: {apps}"

    report = {}
    for app in ("app-a", "app-b", "app-c"):
        series = prom_query(f'nginx_http_response_count_total{{app="{app}"}}')
        assert series and all(item["metric"].get("app") == app for item in series), f"Metric filter leaked across apps for {app}"
        statuses = {item["metric"].get("status") for item in series}
        assert {"200", "301", "403", "404", "500"}.issubset(statuses), f"Missing status series for {app}: {statuses}"
        methods = {item["metric"].get("method") for item in series}
        assert {"GET", "POST"}.issubset(methods), f"Missing GET/POST series for {app}: {methods}"
        buckets = prom_query(f'nginx_http_response_time_seconds_hist_bucket{{app="{app}"}}')
        assert buckets and all(item["metric"].get("app") == app for item in buckets), f"Missing latency buckets for {app}"
        p95 = prom_query(f'histogram_quantile(0.95, sum by (le) (rate(nginx_http_response_time_seconds_hist_bucket{{app="{app}"}}[5m])))')
        assert p95, f"PromQL P95 returned no series for {app}"
        p50 = prom_query(f'histogram_quantile(0.50, sum by (le) (rate(nginx_http_response_time_seconds_hist_bucket{{app="{app}"}}[5m])))')
        p99 = prom_query(f'histogram_quantile(0.99, sum by (le) (rate(nginx_http_response_time_seconds_hist_bucket{{app="{app}"}}[5m])))')
        assert p50 and p99, f"PromQL percentile query returned no series for {app}"

        streams = loki_query(f'{{job="nginx", app="{app}"}}')
        assert streams, f"Loki has no logs for {app}"
        assert all(stream["stream"].get("app") == app for stream in streams), f"Loki filter leaked across apps for {app}"
        entries = []
        for stream in streams:
            for timestamp, line in stream["values"]:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError as error:
                    raise AssertionError(
                        f"Non-JSON Loki event for {app} at {timestamp}: {line!r}"
                    ) from error
        fields = {"time", "app", "method", "path", "status", "request_time", "remote_addr"}
        assert any(fields.issubset(event) for event in entries), f"Access log fields missing for {app}"
        assert all(event.get("app") == app for event in entries), f"Log body app mismatch for {app}"
        report[app] = {
            "statuses": sorted(statuses),
            "p95_seconds": round(float(p95[0]["value"][1]), 3),
            "log_entries": len(entries),
            "methods": sorted(methods),
        }

    targets = get_json(f"{prom}/api/v1/targets")["data"]["activeTargets"]
    target = next((item for item in targets if item["labels"].get("job") == "nginx-access"), None)
    assert target and target["health"] == "up", f"Prometheus exporter target is not up: {target}"
    parse_errors = prom_query("nginx_parse_errors_total")
    assert parse_errors and all(float(item["value"][1]) == 0 for item in parse_errors), f"Exporter parse errors: {parse_errors}"
    return report


def verify_scenarios(security_dashboard):
    subprocess.run(["docker", "compose", "stop", "traffic-generator"], check=True)
    try:
        before = prom_scalar("sum(nginx_http_response_count_total)")
        scan_start_ns = None
        for scenario in ("degradation", "scan", "peak"):
            if scenario == "scan":
                scan_start_ns = time.time_ns()
            subprocess.run(["docker", "compose", "run", "--rm", "--no-deps", "traffic-generator",
                            "python", "-u", "generate.py", "--scenario", scenario, "--duration", "8", "--rps", "4", "--concurrency", "2"], check=True, timeout=40)
            time.sleep(7)
        scanner = next(panel for panel in security_dashboard["panels"] if panel.get("title") == "Observed scanner-like paths")
        path_pattern = scanner["targets"][0]["expr"].split('path=~"', 1)[1].split('"', 1)[0]
        scan_log_query = '{job="nginx",app=~".*"} | path=~"' + path_pattern + '"'
        wait_for(lambda: bool(loki_query(scan_log_query, start_ns=scan_start_ns)),
                 "Scan scenario events did not reach Loki")
        scan = loki_query(scan_log_query, start_ns=scan_start_ns)
        assert scan, "No scanner-like synthetic paths in Loki"
        security_result = verify_security_scenario(security_dashboard, scan_start_ns)
        errors = prom_query('sum(rate(nginx_http_response_count_total{status="500"}[2m]))')
        assert errors and any(float(item["value"][1]) > 0 for item in errors), "Degradation scenario produced no 500 rate"
        after = prom_scalar("sum(nginx_http_response_count_total)")
        assert after > before, "Scenario traffic did not increase Prometheus request counts"
        idle_apps = verify_no_traffic_interval()
        return {"scan_events": sum(len(stream.get("values", [])) for stream in scan), "request_increase": round(after - before, 1), "idle_apps": idle_apps, "security": security_result}
    finally:
        subprocess.run(["docker", "compose", "start", "traffic-generator"], check=True)


def verify_persistence():
    """Run persistence coverage in its own Loki project and named volume."""
    from verify_loki_persistence_isolated import verify_isolated_persistence

    verify_isolated_persistence()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-persistence", action="store_true",
                        help="verify Loki event persistence across a graceful restart in an isolated Compose project")
    parser.add_argument("--verify-scenarios", action="store_true", help="run bounded degradation, scan, and peak scenarios")
    parser.add_argument("--verify-reliability", action="store_true", help="verify log rotation, retention, and recovery from temporary service interruptions")
    args = parser.parse_args()
    security_result = verify_platform_security()
    retention_result = verify_retention_configuration()
    cases = (("", 200), ("redirect", 301), ("forbidden", 403), ("missing", 404), ("error", 500), ("slower", 200), (".env", 404))
    for app in ("app-a", "app-b", "app-c"):
        for path, expected in cases:
            actual = request_status(f"{base}/{app}/{path}")
            assert actual == expected, f"{app}/{path}: expected {expected}, got {actual}"
        post_req = urllib.request.Request(f"{base}/{app}/", data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(post_req, timeout=5) as response:
            assert response.status == 200, f"{app} POST returned {response.status}"

    def expected_statuses_scraped():
        for app in ("app-a", "app-b", "app-c"):
            statuses = {item["metric"].get("status") for item in prom_query(f'nginx_http_response_count_total{{app="{app}"}}')}
            if not {"200", "301", "403", "404", "500"}.issubset(statuses):
                return False
        return True

    wait_for(expected_statuses_scraped, "Prometheus has not scraped all expected statuses for each app")
    report = verify_queries()
    sources, panel_counts, dashboards = verify_dashboard_and_datasources()
    query_counts = verify_dashboard_queries(dashboards)
    category_checks = verify_overview_bar_categories(dashboards["nginx-overview"])
    application_detail_checks = verify_application_detail(dashboards["nginx-application-detail"])
    live_logs_checks = verify_live_logs(dashboards["nginx-live-logs"])
    live_websocket = verify_grafana_live_websocket()
    scenario_result = verify_scenarios(dashboards["nginx-security"]) if args.verify_scenarios else None
    if args.verify_persistence:
        verify_persistence()
        report = verify_queries()
        sources, panel_counts, dashboards = verify_dashboard_and_datasources()
        query_counts = verify_dashboard_queries(dashboards)
        application_detail_checks = verify_application_detail(dashboards["nginx-application-detail"])
        live_logs_checks = verify_live_logs(dashboards["nginx-live-logs"])
    reliability_result = verify_rotation_and_recovery() if args.verify_reliability else None
    for app, result in report.items():
        print(f"{app}: status={','.join(result['statuses'])}; methods={','.join(result['methods'])}; p95={result['p95_seconds']}s; Loki entries={result['log_entries']}")
    suffix = "; isolated Loki persistence regression passed" if args.verify_persistence else ""
    print(f"OK: Prometheus target up, zero exporter parse errors; Grafana sources={','.join(sources)}, panels={panel_counts}, verified panel queries={query_counts}, Overview app category/filter checks={category_checks}, Application Detail checks={application_detail_checks}, Live Logs checks={live_logs_checks}, Grafana Live websocket={live_websocket}; security={security_result}; retention={retention_result}{suffix}")
    if scenario_result:
        print(f"OK: bounded scenarios produced scan_events={scenario_result['scan_events']}, request increase={scenario_result['request_increase']}; no-traffic zero checks={scenario_result['idle_apps']}")
    if reliability_result:
        print(f"OK: reliability={reliability_result}")


if __name__ == "__main__":
    main()
