"""Exercise provisioned Grafana alerts and local delivery using bounded lab traffic."""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import verify_pipeline as pipeline


ROOT = os.path.dirname(os.path.dirname(__file__))
EXPECTED_RULES = {
    "app_unavailable", "nginx_unavailable", "exporter_unavailable", "alloy_unavailable",
    "loki_unavailable", "prometheus_config_failed", "exporter_parse_errors",
    "loki_ingestion_failures", "alloy_dropped_logs",
    "http_5xx_warning", "http_5xx_critical", "http_p95_warning", "http_p95_critical",
    "prometheus_tsdb_storage_warning", "prometheus_tsdb_storage_critical",
}


def grafana_json(path):
    token = base64.b64encode(
        f"{pipeline.grafana_user}:{pipeline.grafana_password}".encode()
    ).decode()
    deadline = time.time() + 45
    last_error = None
    while time.time() < deadline:
        request = urllib.request.Request(pipeline.grafana + path)
        request.add_header("Authorization", f"Basic {token}")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.load(response)
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as error:
            last_error = error
            time.sleep(2)
    raise AssertionError(f"Grafana API unavailable at {path}: {last_error}")


def rule_inventory():
    provisioned = grafana_json("/api/v1/provisioning/alert-rules")
    rules = {rule.get("uid"): rule for rule in provisioned}
    assert EXPECTED_RULES <= set(rules), f"Missing provisioned alerts: {EXPECTED_RULES - set(rules)}"
    for uid in EXPECTED_RULES:
        rule = rules[uid]
        assert rule.get("noDataState") == "NoData", (uid, rule.get("noDataState"))
        assert rule.get("execErrState") == "Error", (uid, rule.get("execErrState"))
        assert rule.get("annotations"), f"{uid} has no operator guidance"
        assert rule.get("labels", {}).get("severity") in {"warning", "critical"}, uid
        query = next((item.get("model", {}).get("expr") for item in rule.get("data", [])
                      if item.get("refId") == "A"), None)
        assert query, f"{uid} has no PromQL query"
        result = pipeline.get_json(f"{pipeline.prom}/api/v1/query?{urllib.parse.urlencode({'query': query})}")
        assert result.get("status") == "success", (uid, query, result)
    contact_points = grafana_json("/api/v1/provisioning/contact-points")
    assert any(point.get("name") == "Local test webhook" for point in contact_points), contact_points
    return rules


def active_rule_states():
    # Grafana's Prometheus-compatible endpoint includes Normal/Pending/Firing state.
    result = grafana_json("/api/prometheus/grafana/api/v1/rules")
    groups = result.get("data", {}).get("groups", [])
    inventory = {}
    for group in groups:
        for rule in group.get("rules", []):
            uid = rule.get("uid") or rule.get("name")
            inventory[uid] = rule
            for alert in rule.get("alerts", []):
                labels = alert.get("labels", {})
                inventory[(labels.get("alertname", uid), labels.get("app", ""))] = alert
    return inventory


def state_of(uid, app=""):
    rules = active_rule_states()
    rule = rules.get(uid)
    if not rule:
        # Prometheus-compatible response uses rule titles for rule groups on some Grafana builds.
        aliases = {
            "app_unavailable": "Application unavailable", "nginx_unavailable": "Nginx unavailable",
            "http_5xx_warning": "Elevated HTTP 5xx ratio", "http_5xx_critical": "Critical HTTP 5xx ratio",
            "http_p95_warning": "Elevated HTTP P95 latency", "http_p95_critical": "Critical HTTP P95 latency",
        }
        rule = rules.get(aliases.get(uid, uid))
    if not rule:
        return None
    alerts = rule.get("alerts", [])
    if app:
        for alert in alerts:
            if alert.get("labels", {}).get("app") == app:
                state = alert.get("state", rule.get("state"))
                return {"inactive": "Normal", "pending": "Pending", "firing": "Alerting"}.get(state, state)
    state = rule.get("state") or (alerts[0].get("state") if alerts else None)
    return {"inactive": "Normal", "pending": "Pending", "firing": "Alerting"}.get(state, state)


def receiver_events():
    completed = subprocess.run(
        ["docker", "compose", "exec", "-T", "grafana", "wget", "-qO-",
         "http://alert-receiver:8081/received"],
        cwd=ROOT, check=True, capture_output=True, text=True, timeout=15,
    )
    return json.loads(completed.stdout)


def wait_state(uid, expected, app="", timeout=90):
    deadline = time.time() + timeout
    observed = None
    while time.time() < deadline:
        observed = state_of(uid, app)
        if observed in expected:
            return observed
        time.sleep(3)
    raise AssertionError(f"{uid} app={app}: expected {expected}, last state {observed}")


def wait_receiver(predicate, message, timeout=90):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = receiver_events()
        if predicate(last):
            return last
        time.sleep(2)
    raise AssertionError(f"{message}; receiver snapshot={last}")


def verify_component_outage(service, uid, alertname, component):
    before_count = receiver_events()["count"]
    pipeline.compose_action("stop", service)
    try:
        state = wait_state(uid, {"Pending", "Alerting"}, timeout=50)
        assert state == "Pending", f"{uid} skipped Pending state: {state}"
        wait_state(uid, {"Alerting"}, timeout=50)
        wait_receiver(lambda data: data["count"] > before_count and any(
            item["alertname"] == alertname and item["component"] == component and item["status"] == "firing"
            for item in data["events"]), f"{alertname} firing webhook was not delivered")
    finally:
        pipeline.compose_action("start", service)
    wait_state(uid, {"Normal"}, timeout=120)
    wait_receiver(lambda data: any(
        item["alertname"] == alertname and item["component"] == component and item["status"] == "resolved"
        for item in data["events"]), f"{alertname} resolved webhook was not delivered")


def stop_generator():
    was_running = bool(pipeline.compose_action("ps", "--status", "running", "--quiet",
                                                "traffic-generator").stdout.strip())
    if was_running:
        pipeline.compose_action("stop", "traffic-generator")
    return was_running


def start_generator():
    pipeline.compose_action("start", "traffic-generator")


def emit(app, path, count, interval=0.0):
    for _ in range(count):
        pipeline.request_status(f"{pipeline.base}/{app}/{path}")
        if interval:
            time.sleep(interval)


def verify_prometheus_targets():
    targets = pipeline.get_json(f"{pipeline.prom}/api/v1/targets")["data"]["activeTargets"]
    health = [target for target in targets if target["labels"].get("job") == "app-health"]
    assert {item["labels"].get("app") for item in health} == {"app-a", "app-b", "app-c"}, health
    assert all(item["health"] == "up" for item in health), health
    for job in ("nginx-health", "nginx-access", "prometheus", "loki", "alloy"):
        found = [item for item in targets if item["labels"].get("job") == job]
        assert found and all(item["health"] == "up" for item in found), (job, found)
    for app in ("app-a", "app-b", "app-c"):
        assert pipeline.prom_query(f'nginx_observability_app_health{{app="{app}"}}')
    assert pipeline.prom_query("nginx_observability_nginx_health")
    assert pipeline.prom_query("nginx_observability_http_5xx_warning_ratio")
    assert pipeline.prom_query("nginx_observability_http_p95_critical_seconds")
    assert pipeline.prom_query("prometheus_tsdb_storage_blocks_bytes")
    assert pipeline.prom_query("loki_ingester_wal_disk_full_failures_total")
    assert pipeline.prom_query("loki_ingester_chunks_flush_failures_total")
    assert pipeline.prom_query("loki_write_dropped_entries_total")


def inspect():
    rules = rule_inventory()
    states = active_rule_states()
    print(json.dumps({
        "provisioned_rule_uids": sorted(rules),
        "state_rule_keys": sorted(str(key) for key in states),
        "states": {uid: state_of(uid) for uid in sorted(EXPECTED_RULES)},
        "target_health": {target["labels"].get("job", "") + ":" + target["labels"].get("app", ""): target["health"]
                          for target in pipeline.get_json(f"{pipeline.prom}/api/v1/targets")["data"]["activeTargets"]},
        "rule_details": {uid: {"state": rule.get("state"), "alerts": rule.get("alerts", [])}
                         for uid, rule in states.items() if isinstance(uid, str) and uid in EXPECTED_RULES},
        "ingestion_metrics": {name: bool(pipeline.prom_query(name)) for name in (
            "loki_ingester_wal_disk_full_failures_total", "loki_ingester_chunks_flush_failures_total",
            "loki_write_dropped_entries_total", "loki_write_sent_entries_total",
        )},
    }, indent=2))


def main():
    if "--inspect" in sys.argv:
        inspect()
        return
    if "--metrics-only" in sys.argv:
        print(json.dumps({name: bool(pipeline.prom_query(name)) for name in (
            "loki_ingester_wal_disk_full_failures_total", "loki_ingester_chunks_flush_failures_total",
            "loki_write_dropped_entries_total", "loki_write_batch_retries_total",
        )}, indent=2))
        return
    rule_inventory()
    verify_prometheus_targets()
    generator_was_running = stop_generator()
    try:
        # No traffic is not a health failure. Give the one-minute traffic queries time to settle.
        print("Checking idle interval and health targets...", flush=True)
        time.sleep(70)
        for uid in ("app_unavailable", "nginx_unavailable", "exporter_unavailable", "alloy_unavailable",
                    "loki_unavailable", "loki_ingestion_failures", "alloy_dropped_logs"):
            assert state_of(uid) not in {"firing", "Alerting", "Pending"}, (uid, state_of(uid))
        no_data_traffic_states = {uid: state_of(uid, "app-a") for uid in ("http_5xx_warning", "http_5xx_critical", "http_p95_warning", "http_p95_critical")}
        assert all(value not in {"firing", "Alerting", "Pending"} for value in no_data_traffic_states.values()), no_data_traffic_states

        # Real app outage while the Nginx health endpoint remains up.
        print("Checking app outage and notification recovery...", flush=True)
        before_events = receiver_events()["count"]
        pipeline.compose_action("stop", "app-a")
        try:
            state = wait_state("app_unavailable", {"pending", "Pending", "firing", "Alerting"}, "app-a", timeout=50)
            assert state in {"pending", "Pending"}, f"App outage skipped Pending: {state}"
            wait_state("app_unavailable", {"firing", "Alerting"}, "app-a", timeout=50)
            assert state_of("nginx_unavailable") == "Normal", "App outage was misclassified as Nginx outage"
            assert state_of("app_unavailable", "app-b") == "Normal"
            assert state_of("app_unavailable", "app-c") == "Normal"
            wait_receiver(lambda data: data["count"] > before_events and any(
                item["alertname"] == "Application unavailable" and item["app"] == "app-a" and item["status"] == "firing"
                for item in data["events"]), "App unavailable firing webhook was not delivered")
        finally:
            pipeline.compose_action("start", "app-a")
        wait_state("app_unavailable", {"normal", "Normal", "resolved"}, "app-a", timeout=90)
        wait_receiver(lambda data: any(
            item["alertname"] == "Application unavailable" and item["app"] == "app-a" and item["status"] == "resolved"
            for item in data["events"]), "App recovery/resolved webhook was not delivered")

        print("Checking exporter and Loki component outages...", flush=True)
        verify_component_outage("nginxlog-exporter", "exporter_unavailable",
                                "Nginx log exporter unavailable", "exporter")
        verify_component_outage("loki", "loki_unavailable", "Loki unavailable", "loki")

        # Sustained error response ratio with enough request volume.
        print("Checking sustained HTTP 5xx alert...", flush=True)
        before_events = receiver_events()["count"]
        emit("app-a", "error", 40, interval=0.5)
        wait_state("http_5xx_critical", {"pending", "Pending", "firing", "Alerting"}, "app-a", timeout=50)
        wait_state("http_5xx_critical", {"firing", "Alerting"}, "app-a", timeout=50)
        wait_state("http_5xx_warning", {"firing", "Alerting"}, "app-a", timeout=50)
        assert state_of("http_5xx_critical", "app-b") == "Normal"
        assert state_of("http_5xx_critical", "app-c") == "Normal"
        wait_receiver(lambda data: data["count"] > before_events and any(
            item["alertname"] == "Critical HTTP 5xx ratio" and item["app"] == "app-a" and item["status"] == "firing"
            for item in data["events"]), "HTTP 5xx webhook was not delivered")
        wait_receiver(lambda data: any(
            item["alertname"] == "Elevated HTTP 5xx ratio" and item["app"] == "app-a" and item["status"] == "firing"
            for item in data["events"]), "HTTP 5xx warning webhook was not delivered")
        wait_state("http_5xx_critical", {"normal", "Normal", "NoData"}, "app-a", timeout=100)

        # Existing /slower route is a deterministic latency signal; continue long enough for P95 `for`.
        print("Checking P95 alert and recovery...", flush=True)
        traffic = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "demo", "traffic-generator", "generate.py"),
             "--scenario", "latency", "--duration", "150", "--rps", "2", "--concurrency", "2",
             "--target", pipeline.base], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        try:
            wait_state("http_p95_warning", {"pending", "Pending"}, "app-a", timeout=75)
            wait_state("http_p95_warning", {"firing", "Alerting"}, "app-a", timeout=150)
        finally:
            traffic.terminate()
            traffic.wait(timeout=10)
        wait_state("http_p95_warning", {"normal", "Normal", "NoData"}, "app-a", timeout=100)

        # App scrape failure is distinct from an idle app and recovers to Normal.
        # (The earlier app outage validates the same transition with notification delivery.)
        verify_prometheus_targets()
        sources, panels, _ = pipeline.verify_dashboard_and_datasources()
        assert set(panels) == {"nginx-overview", "nginx-application-detail", "nginx-live-logs", "nginx-security"}
        print("OK: alert rules provisioned; health/no-traffic, app outage, 5xx, P95, recovery, and local webhook delivery verified")
    finally:
        if generator_was_running:
            start_generator()


if __name__ == "__main__":
    main()
