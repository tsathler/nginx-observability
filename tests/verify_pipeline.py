"""Verify request routing, metrics, logs, Grafana provisioning, and optional persistence."""
import argparse
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

base = os.getenv("LAB_URL", "http://127.0.0.1:8080").rstrip("/")
prom = os.getenv("PROMETHEUS_URL", "http://127.0.0.1:9090").rstrip("/")
loki = os.getenv("LOKI_URL", "http://127.0.0.1:3100").rstrip("/")
grafana = os.getenv("GRAFANA_URL", "http://127.0.0.1:3000").rstrip("/")


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


def get_json(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise AssertionError(f"HTTP {error.code} from {url}: {error.read().decode(errors='replace')}") from error


def prom_query(expression):
    query = urllib.parse.urlencode({"query": expression})
    result = get_json(f"{prom}/api/v1/query?{query}")
    assert result["status"] == "success", result
    return result["data"]["result"]


def grafana_prom_frames(expression):
    body = {
        "queries": [{"refId": "A", "datasource": {"type": "prometheus", "uid": "prometheus"},
                     "expr": expression, "instant": True, "range": False, "format": "time_series",
                     "intervalMs": 10000, "maxDataPoints": 100}],
        "from": "now-15m", "to": "now",
    }
    request = urllib.request.Request(f"{grafana}/api/ds/query", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        result = json.load(response)
    assert result["results"]["A"]["status"] == 200, result
    return result["results"]["A"]["frames"]


def prom_scalar(expression):
    result = prom_query(expression)
    assert result, f"Prometheus returned no value for {expression}"
    return float(result[0]["value"][1])


def loki_query(expression, start_ns=None, end_ns=None):
    end_ns = end_ns or time.time_ns()
    params = {
        "query": expression,
        "start": str(start_ns or end_ns - 600_000_000_000),
        "end": str(end_ns),
        "limit": "200",
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


def verify_dashboard_and_datasources():
    sources = get_json(f"{grafana}/api/datasources")
    assert {source["name"] for source in sources} >= {"Prometheus", "Loki"}, sources
    expected = {
        "nginx-overview": ("Nginx | Overview", 10),
        "nginx-application-detail": ("Nginx | Application Detail", 10),
        "nginx-live-logs": ("Nginx | Live Logs", 2),
        "nginx-security": ("Nginx | Security", 10),
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
                assert bar.get("options", {}).get("xField") == "app", f"{title} does not use app as category"
                assert any(item.get("id") == "labelsToFields" and item.get("options", {}).get("mode") == "columns"
                           for item in bar.get("transformations", [])), f"{title} does not extract app labels into fields"
                assert " by (app) " in bar["targets"][0]["expr"], f"{title} query does not group by app"
            assert not any("429" in panel["title"] for panel in panels), "Overview reserves space for the synthetic zero-only 429 metric"
            assert any("period total" in panel["title"] for panel in panels if panel.get("type") == "barchart")
        if uid != "nginx-overview":
            variables = dashboard.get("templating", {}).get("list", [])
            assert any(variable.get("name") == "app" for variable in variables), f"{uid} has no app selector"
        if uid in ("nginx-application-detail", "nginx-live-logs"):
            assert any(panel.get("type") == "logs" for panel in panels), f"{uid} has no logs visualization"
        if uid == "nginx-live-logs":
            assert any("/explore?panes=" in link.get("url", "") for link in dashboard.get("links", [])), "Live Logs has no Explore link"
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
        for frame in frames:
            fields = frame["schema"]["fields"]
            value_field = next(field for field in fields if field["name"] == "Value")
            if "app" in value_field.get("labels", {}):
                labels.add(value_field["labels"]["app"])
        assert labels == expected, f"{title}: Grafana query frame labels do not identify every app: {labels}"
        selected = grafana_prom_frames(expression.replace('app=~".*"', 'app=~"app-b"'))
        selected_apps = {
            field.get("labels", {}).get("app")
            for frame in selected for field in frame["schema"]["fields"] if field["name"] == "Value"
        }
        assert selected_apps == {"app-b"}, f"{title}: app variable filter leaked: {selected_apps}"
    return len(titles) * 2


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
        entries = [json.loads(line) for stream in streams for _, line in stream["values"]]
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


def verify_scenarios():
    subprocess.run(["docker", "compose", "stop", "traffic-generator"], check=True)
    try:
        before = prom_scalar("sum(nginx_http_response_count_total)")
        for scenario in ("degradation", "scan", "peak"):
            subprocess.run(["docker", "compose", "run", "--rm", "--no-deps", "traffic-generator",
                            "python", "-u", "generate.py", "--scenario", scenario, "--duration", "8", "--rps", "4", "--concurrency", "2"], check=True, timeout=40)
            time.sleep(7)
        wait_for(lambda: bool(loki_query('{job="nginx"} | json | path=~".*(\\\\.env|\\\\.git|wp-admin|wp-login\\\\.php|phpmyadmin|/etc/passwd).*"')),
                 "Scan scenario events did not reach Loki")
        scan = loki_query('{job="nginx"} | json | path=~".*(\\\\.env|\\\\.git|wp-admin|wp-login\\\\.php|phpmyadmin|/etc/passwd).*"')
        assert scan, "No scanner-like synthetic paths in Loki"
        errors = prom_query('sum(rate(nginx_http_response_count_total{status="500"}[2m]))')
        assert errors and any(float(item["value"][1]) > 0 for item in errors), "Degradation scenario produced no 500 rate"
        after = prom_scalar("sum(nginx_http_response_count_total)")
        assert after > before, "Scenario traffic did not increase Prometheus request counts"
        return {"scan_events": sum(len(stream.get("values", [])) for stream in scan), "request_increase": round(after - before, 1)}
    finally:
        subprocess.run(["docker", "compose", "start", "traffic-generator"], check=True)


def verify_persistence():
    marker = f"persist-{uuid.uuid4().hex}"
    before = prom_scalar('sum(nginx_http_response_count_total{app="app-a"})')
    marker_ns = time.time_ns()
    status = request_status(f"{base}/app-a/?marker={marker}")
    assert status == 200, f"Persistence marker request returned HTTP {status}"

    wait_for(lambda: prom_scalar('sum(nginx_http_response_count_total{app="app-a"})') > before,
             "Prometheus did not scrape the marker request")
    marker_query = f'{{job="nginx", app="app-a"}} | json | request=~".*{marker}.*"'
    wait_for(lambda: bool(loki_query(marker_query, marker_ns - 5_000_000_000)), "Loki did not ingest the marker request")
    recorded_metric = prom_scalar('sum(nginx_http_response_count_total{app="app-a"})')

    subprocess.run(["docker", "compose", "restart", "prometheus", "loki"], check=True)
    wait_for(lambda: bool(prom_query('up{job="nginx-access"}')) and
             prom_scalar('sum(nginx_http_response_count_total{app="app-a"})') >= recorded_metric,
             "Prometheus data did not survive restart", timeout=120)
    wait_for(lambda: bool(loki_query(marker_query, marker_ns - 5_000_000_000)),
             "Loki marker did not survive restart", timeout=120)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-persistence", action="store_true", help="restart Prometheus and Loki and verify retained data")
    parser.add_argument("--verify-scenarios", action="store_true", help="run bounded degradation, scan, and peak scenarios")
    args = parser.parse_args()
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
    scenario_result = verify_scenarios() if args.verify_scenarios else None
    if args.verify_persistence:
        verify_persistence()
        report = verify_queries()
        sources, panel_counts, dashboards = verify_dashboard_and_datasources()
        query_counts = verify_dashboard_queries(dashboards)
    for app, result in report.items():
        print(f"{app}: status={','.join(result['statuses'])}; methods={','.join(result['methods'])}; p95={result['p95_seconds']}s; Loki entries={result['log_entries']}")
    suffix = "; persistence survived Prometheus/Loki restart" if args.verify_persistence else ""
    print(f"OK: Prometheus target up, zero exporter parse errors; Grafana sources={','.join(sources)}, panels={panel_counts}, verified panel queries={query_counts}, app category/filter checks={category_checks}{suffix}")
    if scenario_result:
        print(f"OK: bounded scenarios produced scan_events={scenario_result['scan_events']}, request increase={scenario_result['request_increase']}")


if __name__ == "__main__":
    main()
