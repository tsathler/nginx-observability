"""Offline checks for scripts/install_grafana.py (no Grafana needed).

  * every dashboard and alert string has a pt-BR translation;
  * --lang both yields English and Portuguese dashboards with unique UIDs, links to the
    dashboards of the same language and a language switch;
  * translated tables stay consistent: overrides and sorting refer to the translated columns;
  * lab-only rules are left out unless asked for; Portuguese alerts link Portuguese dashboards;
  * carousel pages pin server and app and keep UIDs within Grafana's 40-character limit.

Run: python tests/verify_grafana_install.py
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import install_grafana as ig  # noqa: E402

UIDS = {"prometheus": "nginx-obs-prometheus", "loki": "nginx-obs-loki"}


def catalog_coverage():
    catalog = ig.load_catalog("pt-BR")
    missing = set()
    for path in sorted(ig.DASHBOARDS.glob("*.json")):
        missing |= {text for text in ig.dashboard_strings(json.loads(path.read_text(encoding="utf-8"))) if text not in catalog}
    bundle = json.loads(ig.ALERT_BUNDLE.read_text(encoding="utf-8"))
    for group in bundle["groups"]:
        for rule in group["rules"]:
            texts = [rule["title"]] + [text for key, text in rule["annotations"].items() if not key.startswith("__")]
            missing |= {text for text in texts if text not in catalog}
    assert not missing, "Missing pt-BR translations:\n" + "\n".join(sorted(missing))
    unused = set(catalog) - {"_comment"} - collect_all_sources()
    assert not unused, "Stale pt-BR entries (no longer in the dashboards or alerts):\n" + "\n".join(sorted(unused))


def collect_all_sources():
    found = set()
    for path in sorted(ig.DASHBOARDS.glob("*.json")):
        found |= ig.dashboard_strings(json.loads(path.read_text(encoding="utf-8")))
    for group in json.loads(ig.ALERT_BUNDLE.read_text(encoding="utf-8"))["groups"]:
        for rule in group["rules"]:
            found.add(rule["title"])
            found |= {text for key, text in rule["annotations"].items() if not key.startswith("__")}
    return found


def tables_consistent(dashboard):
    for panel in dashboard["panels"]:
        organize = [t["options"] for t in panel.get("transformations", []) if t["id"] == "organize"]
        if not organize:
            continue
        renames = organize[-1].get("renameByName", {})
        shown = set(renames.values()) | {field for field in organize[-1].get("indexByName", {}) if field not in renames}
        for override in panel.get("fieldConfig", {}).get("overrides", []):
            matcher = override["matcher"]
            if matcher["id"] == "byName" and matcher["options"] not in ("request_time",):
                assert matcher["options"] in shown, (dashboard["uid"], panel["title"], matcher["options"], shown)
        for entry in panel.get("options", {}).get("sortBy", []):
            assert entry["displayName"] in shown, (dashboard["uid"], panel["title"], entry["displayName"], shown)


def dashboards_both():
    built = ig.build_dashboards("both", UIDS)
    uids = [d["uid"] for d in built]
    assert len(uids) == 8 and len(set(uids)) == 8, uids
    titles = [d["title"] for d in built]
    assert len(set(titles)) == 8, titles
    by_uid = {d["uid"]: d for d in built}
    for base in ig.DASHBOARD_UIDS:
        en, pt = by_uid[base], by_uid[base + "-pt-br"]
        assert pt["title"] != en["title"], base
        en_links = {link["title"]: link["url"] for link in en["links"]}
        pt_links = {link["title"]: link["url"] for link in pt["links"]}
        assert en_links["Português (BR)"] == f"/d/{base}-pt-br", en_links
        assert pt_links["English"] == f"/d/{base}", pt_links
        assert all(link.get("includeVars") and link.get("keepTime") for link in pt["links"] if link["title"] in ("English",))
        text = json.dumps(pt)
        assert not re.search(r"/d/nginx-(overview|application-detail|live-logs|security)(?!-pt-br)[/\"?]", text.replace(f'"/d/{base}"', "")), \
            f"{pt['uid']} links an English dashboard"
        assert "nginx-obs-prometheus" in text and '"uid": "prometheus"' not in text
        tables_consistent(en)
        tables_consistent(pt)
    overview = by_uid["nginx-overview-pt-br"]
    assert overview["title"] == "Nginx | Visão geral"
    assert any(v["label"] == "Servidor" for v in overview["templating"]["list"])
    english_only = ig.build_dashboards("en", UIDS)
    assert [d["uid"] for d in english_only] == sorted(ig.DASHBOARD_UIDS, key=lambda uid: next(
        p.name for p in ig.DASHBOARDS.glob("*.json") if json.loads(p.read_text(encoding="utf-8"))["uid"] == uid))
    assert all(link["title"] not in ("English", "Português (BR)") for d in english_only for link in d.get("links", []))


def alerts():
    groups = ig.build_alert_groups(UIDS, "nginx-observability", "pt-BR", include_lab_rules=False)
    rules = {rule["uid"]: rule for group in groups for rule in group["rules"]}
    assert not ig.LAB_ONLY_RULES & set(rules), "lab-only rules must be skipped by default"
    assert "agent_silent" in rules and rules["agent_silent"]["title"] == "Agente do servidor monitorado parou de enviar"
    assert rules["agent_silent"]["annotations"]["__dashboardUid__"] == "nginx-overview-pt-br"
    assert rules["http_p95_warning"]["data"][0]["datasourceUid"] == "nginx-obs-prometheus"
    with_lab = ig.build_alert_groups(UIDS, "nginx-observability", "en", include_lab_rules=True)
    lab_rules = {rule["uid"]: rule for group in with_lab for rule in group["rules"]}
    assert ig.LAB_ONLY_RULES <= set(lab_rules)
    assert lab_rules["agent_silent"]["annotations"]["__dashboardUid__"] == "nginx-overview"


def carousel():
    template = next(d for d in ig.build_dashboards("pt-BR", UIDS) if d["uid"] == "nginx-application-detail-pt-br")
    page = ig.carousel_page(template, "web-01", "portal")
    assert page["uid"] == "nginx-carousel-web-01-portal"
    current = {v["name"]: v["current"]["value"] for v in page["templating"]["list"] if v["name"] in ("server", "app")}
    assert current == {"server": "web-01", "app": "portal"}, current
    assert ig.CAROUSEL_TAG in page["tags"] and page["title"].endswith("portal (web-01)")
    long_uid = ig.carousel_uid("a-very-long-server-name.example.internal", "an-application-with-a-long-name")
    assert len(long_uid) <= 40 and long_uid.startswith("nginx-carousel-"), long_uid


def main():
    for check in (catalog_coverage, dashboards_both, alerts, carousel):
        check()
        print(f"ok  {check.__name__}")


if __name__ == "__main__":
    main()
