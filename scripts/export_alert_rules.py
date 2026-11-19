"""Regenerate deploy/grafana/alert-rules.json from the lab Grafana.

config/grafana/provisioning/alerting/alerts.yml stays the source of truth. Grafana resolves
its YAML anchors and defaults; this script saves that resolved form as JSON so
scripts/install_grafana.py can install the rules through the HTTP API with no YAML parser.
Run after editing alerts.yml and reloading the lab Grafana; tests/verify_alerting.py fails
while the bundle is out of date.

Usage: python scripts/export_alert_rules.py   (reads GRAFANA_URL / credentials like the tests)
"""
import base64
import json
import os
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "deploy" / "grafana" / "alert-rules.json"


def lab_credentials():
    values = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    user = os.getenv("GRAFANA_ADMIN_USER", values.get("GRAFANA_ADMIN_USER", "admin"))
    password = os.getenv("GRAFANA_ADMIN_PASSWORD", values.get("GRAFANA_ADMIN_PASSWORD", ""))
    return user, password


def exported_groups(grafana, user, password):
    request = urllib.request.Request(f"{grafana}/api/v1/provisioning/alert-rules/export?format=json")
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    request.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)["groups"]


def normalized(groups):
    """Drop what depends on the target Grafana (org, folder) and sort for stable diffs."""
    result = []
    for group in sorted(groups, key=lambda item: item["name"]):
        rules = []
        for rule in sorted(group["rules"], key=lambda item: item["uid"]):
            rule = {key: value for key, value in rule.items() if key not in ("orgId", "folderUID", "ruleGroup")}
            rules.append(rule)
        result.append({"name": group["name"], "interval": group["interval"], "rules": rules})
    return result


def main():
    grafana = os.getenv("GRAFANA_URL", "http://127.0.0.1:3000")
    user, password = lab_credentials()
    bundle = {
        "source": "config/grafana/provisioning/alerting/alerts.yml (resolved by Grafana)",
        "groups": normalized(exported_groups(grafana, user, password)),
    }
    BUNDLE.parent.mkdir(parents=True, exist_ok=True)
    BUNDLE.write_text(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    rules = sum(len(group["rules"]) for group in bundle["groups"])
    print(f"Wrote {BUNDLE.relative_to(ROOT)}: {len(bundle['groups'])} group(s), {rules} rules")


if __name__ == "__main__":
    main()
