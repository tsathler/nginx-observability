"""Install this stack's datasources, dashboards and alert rules into an existing Grafana.

For the organization's shared Grafana (Marco 04), where this project does not run its own
Grafana. Uses only the HTTP API and the Python standard library, so nothing is copied into
the Grafana container and its own provisioning is left alone.

What it creates or updates (idempotent; run again after a git pull):
  * datasources "Nginx Observability - Prometheus" / "- Loki" with their own UIDs, so they
    never collide with datasources the Grafana already has;
  * folder "Nginx Observability" with the four dashboards (datasource UIDs rewritten);
  * alert rule group(s) from deploy/grafana/alert-rules.json in that folder.
It never changes contact points or notification policies: route the rules' labels
(severity, component, server, app) in the existing policy tree.

Authentication: a service account token with the Admin role in GRAFANA_TOKEN.

Example (on the central server):
  GRAFANA_TOKEN=... python3 scripts/install_grafana.py --grafana-url http://127.0.0.1:3000
"""
import argparse
import copy
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DASHBOARDS = ROOT / "config" / "grafana" / "dashboards"
ALERT_BUNDLE = ROOT / "deploy" / "grafana" / "alert-rules.json"
LAB_UIDS = {"prometheus": "prometheus", "loki": "loki"}  # datasource UIDs used in the repo


class Grafana:
    def __init__(self, url, token, dry_run):
        self.url = url.rstrip("/")
        self.token = token
        self.dry_run = dry_run

    def call(self, method, path, body=None, allow_404=False, headers=None):
        if self.dry_run and method != "GET":
            print(f"  [dry-run] {method} {path}")
            return {}
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.url + path, data=data, method=method)
        request.add_header("Authorization", f"Bearer {self.token}")
        request.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = response.read()
                return json.loads(payload) if payload else {}
        except urllib.error.HTTPError as error:
            if allow_404 and error.code == 404:
                return None
            detail = error.read().decode(errors="replace")[:500]
            raise SystemExit(f"Grafana API {method} {path} failed: HTTP {error.code}: {detail}")


def rewrite_datasources(value, uids):
    """Point every datasource reference (objects, alert queries, Explore links) at the new UIDs."""
    if isinstance(value, dict):
        result = {key: rewrite_datasources(item, uids) for key, item in value.items()}
        if result.get("type") in uids and result.get("uid") == LAB_UIDS[result["type"]]:
            result["uid"] = uids[result["type"]]
        if result.get("datasourceUid") in LAB_UIDS.values():
            kind = next(k for k, v in LAB_UIDS.items() if v == result["datasourceUid"])
            result["datasourceUid"] = uids[kind]
        return result
    if isinstance(value, list):
        return [rewrite_datasources(item, uids) for item in value]
    if isinstance(value, str) and "%22" in value:
        for kind, lab_uid in LAB_UIDS.items():
            for key in ("datasource", "uid"):
                value = value.replace(f"%22{key}%22%3A%22{lab_uid}%22", f"%22{key}%22%3A%22{uids[kind]}%22")
        return value
    return value


def ensure_datasource(grafana, kind, uid, name, url):
    body = {"uid": uid, "name": name, "type": kind, "access": "proxy", "url": url, "isDefault": False}
    by_name = grafana.call("GET", f"/api/datasources/name/{urllib.parse.quote(name)}", allow_404=True)
    if by_name and by_name.get("uid") != uid:
        raise SystemExit(f"A datasource named {name!r} already exists with UID {by_name.get('uid')!r}; "
                         f"rename it or pass --datasource-prefix.")
    current = grafana.call("GET", f"/api/datasources/uid/{uid}", allow_404=True)
    if current is None:
        grafana.call("POST", "/api/datasources", body)
        print(f"  created datasource {name} ({uid}) -> {url}")
    else:
        grafana.call("PUT", f"/api/datasources/uid/{uid}", {**current, **body})
        print(f"  updated datasource {name} ({uid}) -> {url}")


def ensure_folder(grafana, uid, title):
    if grafana.call("GET", f"/api/folders/{uid}", allow_404=True) is None:
        grafana.call("POST", "/api/folders", {"uid": uid, "title": title})
        print(f"  created folder {title} ({uid})")
    else:
        print(f"  folder {title} ({uid}) exists")


def install_dashboards(grafana, folder_uid, uids):
    for path in sorted(DASHBOARDS.glob("*.json")):
        dashboard = rewrite_datasources(json.loads(path.read_text(encoding="utf-8")), uids)
        dashboard.pop("id", None)
        grafana.call("POST", "/api/dashboards/db", {
            "dashboard": dashboard, "folderUid": folder_uid, "overwrite": True,
            "message": "nginx-observability install_grafana.py",
        })
        print(f"  dashboard {dashboard['title']} ({dashboard['uid']})")


def seconds(duration):
    units = {"s": 1, "m": 60, "h": 3600}
    return int(duration[:-1]) * units[duration[-1]] if duration[-1] in units else int(duration)


def install_alerts(grafana, folder_uid, uids, interval_override):
    bundle = json.loads(ALERT_BUNDLE.read_text(encoding="utf-8"))
    for group in bundle["groups"]:
        rules = []
        for source in group["rules"]:
            rule = rewrite_datasources(copy.deepcopy(source), uids)
            # The export repeats the dashboard link (already in the __dashboardUid__/__panelId__
            # annotations) as fields the provisioning API rejects; unlinked rules carry "" and 0.
            rule.pop("dashboardUid", None)
            rule.pop("panelId", None)
            rule.update({"folderUID": folder_uid, "ruleGroup": group["name"]})
            rules.append(rule)
        interval = interval_override or group["interval"]
        grafana.call("PUT", f"/api/v1/provisioning/folder/{folder_uid}/rule-groups/{urllib.parse.quote(group['name'])}",
                     {"title": group["name"], "folderUid": folder_uid, "interval": seconds(interval), "rules": rules})
        print(f"  alert group {group['name']}: {len(rules)} rules, every {interval}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--grafana-url", default=os.getenv("GRAFANA_URL", "http://127.0.0.1:3000"))
    parser.add_argument("--prometheus-url", default="http://nginx-obs-prometheus:9090",
                        help="URL of the central Prometheus as seen from the Grafana server")
    parser.add_argument("--loki-url", default="http://nginx-obs-loki:3100",
                        help="URL of the central Loki as seen from the Grafana server")
    parser.add_argument("--datasource-prefix", default="nginx-obs",
                        help="UID prefix for the datasources (default: nginx-obs)")
    parser.add_argument("--folder-uid", default="nginx-observability")
    parser.add_argument("--folder-title", default="Nginx Observability")
    parser.add_argument("--alert-interval", help="evaluation interval for the rule group, e.g. 30s or 1m")
    parser.add_argument("--skip-alerts", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="read only; print the writes it would make")
    args = parser.parse_args()

    token = os.getenv("GRAFANA_TOKEN")
    if not token:
        raise SystemExit("Set GRAFANA_TOKEN to a service account token with the Admin role.")
    grafana = Grafana(args.grafana_url, token, args.dry_run)
    health = grafana.call("GET", "/api/health")
    print(f"Grafana {health.get('version')} at {args.grafana_url}")

    uids = {"prometheus": f"{args.datasource_prefix}-prometheus", "loki": f"{args.datasource_prefix}-loki"}
    print("Datasources")
    ensure_datasource(grafana, "prometheus", uids["prometheus"], "Nginx Observability - Prometheus", args.prometheus_url)
    ensure_datasource(grafana, "loki", uids["loki"], "Nginx Observability - Loki", args.loki_url)
    print("Folder")
    ensure_folder(grafana, args.folder_uid, args.folder_title)
    print("Dashboards")
    install_dashboards(grafana, args.folder_uid, uids)
    if not args.skip_alerts:
        print("Alert rules")
        install_alerts(grafana, args.folder_uid, uids, args.alert_interval)
    print("Done. Route the alerts in the existing notification policies (labels: severity, component, server, app).")


if __name__ == "__main__":
    sys.exit(main())
