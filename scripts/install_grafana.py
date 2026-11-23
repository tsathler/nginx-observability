"""Install this stack's datasources, dashboards and alert rules into an existing Grafana.

For the organization's shared Grafana (Marco 04), where this project does not run its own
Grafana. Uses only the HTTP API and the Python standard library, so nothing is copied into
the Grafana container and its own provisioning is left alone.

What it creates or updates (idempotent; run again after a git pull):
  * datasources "Nginx Observability - Prometheus" / "- Loki" with their own UIDs, so they
    never collide with datasources the Grafana already has;
  * folder "Nginx Observability" with the four dashboards (datasource UIDs rewritten), in
    English, Brazilian Portuguese (--lang pt-BR) or both with a language switch (--lang both);
  * alert rule group(s) from deploy/grafana/alert-rules.json in that folder, without the
    lab-only rules that need the lab's health endpoints and exporter;
  * optionally (--carousel) an "Application carousel" / "Carrossel das aplicações" button in
    Application Detail that rotates one pinned page per (server, app) full screen (a Grafana
    playlist in kiosk mode).
It only overwrites or deletes objects it created: dashboards in its own folder, carousel pages
tagged nginx-carousel, and playlists whose pages are all carousel pages.
It never changes contact points or notification policies: route the rules' labels
(severity, component, server, app) in the existing policy tree.

Authentication: a service account token with the Admin role in GRAFANA_TOKEN.

Example (on the central server; read -rs keeps the token out of the shell history):
  read -rs GRAFANA_TOKEN && export GRAFANA_TOKEN
  python3 scripts/install_grafana.py --grafana-url http://127.0.0.1:3000 --lang both --carousel --dry-run
"""
import argparse
import copy
import hashlib
import json
import os
import pathlib
import ipaddress
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DASHBOARDS = ROOT / "config" / "grafana" / "dashboards"
ALERT_BUNDLE = ROOT / "deploy" / "grafana" / "alert-rules.json"
CATALOGS = ROOT / "deploy" / "grafana" / "i18n"
LAB_UIDS = {"prometheus": "prometheus", "loki": "loki"}  # datasource UIDs used in the repo
DASHBOARD_UIDS = ("nginx-overview", "nginx-application-detail", "nginx-live-logs", "nginx-security")
APP_DETAIL_UID = "nginx-application-detail"
# Rules that watch the lab's own health endpoints and nginxlog-exporter. Monitored servers use
# the Alloy agent instead, where "Monitored server agent stopped sending" covers the gap.
LAB_ONLY_RULES = {"app_unavailable", "nginx_unavailable", "exporter_unavailable"}
CAROUSEL_TAG = "nginx-carousel"
LANGUAGES = {"en": "English", "pt-BR": "Português (BR)"}
LANG_SUFFIX = {"en": "", "pt-BR": "-pt-br"}

# Dashboard keys whose string value is shown to people (translated when a catalog has them).
TEXT_KEYS = {"title", "description", "label", "noValue", "axisLabel", "tooltip", "content", "displayName", "text"}
# Raw log fields that tables show under their own name unless a translation renames them.
RAW_FIELDS = ("body_bytes_sent",)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib would follow a redirect and resend the Authorization header to the new host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, f"refusing redirect to {newurl}", headers, fp)


class Grafana:
    def __init__(self, url, token, dry_run, ca_file=None):
        self.url = url.rstrip("/")
        self.token = token
        self.dry_run = dry_run
        context = ssl.create_default_context(cafile=ca_file)
        self.opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=context))

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
            with self.opener.open(request, timeout=30) as response:
                payload = response.read()
                return json.loads(payload) if payload else {}
        except urllib.error.HTTPError as error:
            if allow_404 and error.code == 404:
                return None
            detail = (error.read() if error.fp else b"").decode(errors="replace")[:500]
            raise SystemExit(f"Grafana API {method} {path} failed: HTTP {error.code}: {detail}")

    def did(self, done, planned):
        """Past tense for real runs, "would ..." for --dry-run, so a rehearsal never reads as done."""
        return planned if self.dry_run else done


def is_loopback(url):
    host = urllib.parse.urlsplit(url).hostname or ""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


# --- datasources -------------------------------------------------------------------------

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
    if current and current.get("type") != kind:
        raise SystemExit(f"Datasource UID {uid!r} already exists as type {current.get('type')!r} "
                         f"({current.get('name')!r}); pass another --datasource-prefix.")
    if current is None:
        grafana.call("POST", "/api/datasources", body)
        print(f"  {grafana.did('created', 'would create')} datasource {name} ({uid}) -> {url}")
    else:
        grafana.call("PUT", f"/api/datasources/uid/{uid}", {**current, **body})
        print(f"  {grafana.did('updated', 'would update')} datasource {name} ({uid}) -> {url}")


def ensure_folder(grafana, uid, title, parent_uid=None):
    if grafana.call("GET", f"/api/folders/{uid}", allow_404=True) is None:
        body = {"uid": uid, "title": title}
        if parent_uid:
            body["parentUid"] = parent_uid
        grafana.call("POST", "/api/folders", body)
        print(f"  {grafana.did('created', 'would create')} folder {title} ({uid})")
    else:
        print(f"  folder {title} ({uid}) exists")


# --- translation -------------------------------------------------------------------------

def load_catalog(lang):
    if lang == "en":
        return {}
    path = CATALOGS / f"{lang}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def dashboard_strings(dashboard):
    """Every human-readable string the translation step looks at, for catalog coverage checks."""
    found = set()

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in TEXT_KEYS and isinstance(item, str):
                    found.add(item)
            if value.get("id") == "organize" and isinstance(value.get("options"), dict):
                renames = value["options"].get("renameByName", {})
                found.update(name for name in renames.values() if isinstance(name, str))
                found.update(field for field in value["options"].get("indexByName", {}) if field not in renames)
                excluded = value["options"].get("excludeByName", {})
                if "Line" in excluded:  # tables built from parsed Loki lines
                    found.update(field for field in RAW_FIELDS if not excluded.get(field))
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(dashboard)
    return {text for text in found if needs_translation(text)}


def needs_translation(text):
    """Skip values that are data rather than prose: status codes, methods, variables, field ids."""
    if not re.search(r"[A-Za-z]{2}", text):
        return False
    return not re.fullmatch(r"(\dxx|GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS|\$\{?\w+.*|server|app|method|status|path"
                            r"|remote_addr|request_time|Value( #A)?)", text)


def translate_dashboard(dashboard, catalog):
    """Translate titles, descriptions, labels and table columns. Field names used by queries and
    transformations stay as they are; only what people read changes."""
    if not catalog:
        return dashboard

    def tr(text):
        return catalog.get(text, text)

    def walk(value):
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if key in TEXT_KEYS and isinstance(item, str):
                    result[key] = tr(item)
                elif key == "matcher" and isinstance(item, dict) and item.get("id") == "byName":
                    # Overrides match the displayed column name, which is translated below.
                    result[key] = {**item, "options": tr(item.get("options", ""))}
                elif key == "sortBy" and isinstance(item, list):
                    result[key] = [{**entry, "displayName": tr(entry.get("displayName", ""))}
                                   if isinstance(entry, dict) else entry for entry in item]
                else:
                    result[key] = walk(item)
            if result.get("id") == "organize" and isinstance(result.get("options"), dict):
                options = result["options"]
                renames = {key: tr(name) for key, name in options.get("renameByName", {}).items()}
                # Columns shown under their own field name (Time, the calculated duration) are
                # renamed here, after every transformation that refers to them.
                for field in options.get("indexByName", {}):
                    if field not in renames and field in catalog:
                        renames[field] = catalog[field]
                if "Line" in options.get("excludeByName", {}):
                    for field in RAW_FIELDS:
                        if not options["excludeByName"].get(field) and field in catalog:
                            renames.setdefault(field, catalog[field])
                options["renameByName"] = renames
            return result
        if isinstance(value, list):
            return [walk(item) for item in value]
        return value

    return walk(dashboard)


def localize_uids(value, lang):
    """Point links and alert annotations at the dashboards of the chosen language."""
    suffix = LANG_SUFFIX[lang]
    if not suffix:
        return value
    pattern = re.compile(r"/d/(" + "|".join(DASHBOARD_UIDS) + r")(?=[/?\"'&]|$)")

    def walk(item):
        if isinstance(item, dict):
            return {key: (f"{child}{suffix}" if key in ("uid", "__dashboardUid__") and child in DASHBOARD_UIDS else walk(child))
                    for key, child in item.items()}
        if isinstance(item, list):
            return [walk(child) for child in item]
        if isinstance(item, str):
            return pattern.sub(lambda match: f"/d/{match.group(1)}{suffix}", item)
        return item

    return walk(value)


def language_link(base_uid, target_lang):
    return {
        "title": LANGUAGES[target_lang], "type": "link", "icon": "info",
        "url": f"/d/{base_uid}{LANG_SUFFIX[target_lang]}", "includeVars": True, "keepTime": True,
        "targetBlank": False, "asDropdown": False, "tags": [],
        "tooltip": "Abrir esta página em português" if target_lang == "pt-BR" else "Open this page in English",
    }


def build_dashboards(lang, uids):
    """Return the dashboards to install for --lang en / pt-BR / both."""
    languages = ["en", "pt-BR"] if lang == "both" else [lang]
    built = []
    for path in sorted(DASHBOARDS.glob("*.json")):
        source = rewrite_datasources(json.loads(path.read_text(encoding="utf-8")), uids)
        source.pop("id", None)
        base_uid = source["uid"]
        for language in languages:
            dashboard = localize_uids(translate_dashboard(copy.deepcopy(source), load_catalog(language)), language)
            if lang == "both":
                other = "pt-BR" if language == "en" else "en"
                dashboard.setdefault("links", []).append(language_link(base_uid, other))
            built.append(dashboard)
    return built


def check_owned_dashboard(grafana, uid, folder_uids):
    """Refuse to overwrite a dashboard with the same UID that lives outside this stack's folders."""
    current = grafana.call("GET", f"/api/dashboards/uid/{uid}", allow_404=True)
    if current is None:
        return
    folder = (current.get("meta") or {}).get("folderUid", "")
    if folder not in folder_uids:
        raise SystemExit(f"Dashboard UID {uid!r} already exists in another folder ({folder or 'General'!r}) "
                         f"and was not created by this installer; move or rename it first.")


def install_dashboards(grafana, folder_uid, dashboards):
    for dashboard in dashboards:
        check_owned_dashboard(grafana, dashboard["uid"], {folder_uid})
        grafana.call("POST", "/api/dashboards/db", {
            "dashboard": dashboard, "folderUid": folder_uid, "overwrite": True,
            "message": "nginx-observability install_grafana.py",
        })
        print(f"  dashboard {dashboard['title']} ({dashboard['uid']})")


# --- alerts ------------------------------------------------------------------------------

def seconds(duration):
    """'30s', '1m', '1m30s', '2h' or a plain number of seconds."""
    if re.fullmatch(r"\d+", duration):
        return int(duration)
    parts = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", duration)
    if not duration or not parts or not any(parts.groups()):
        raise SystemExit(f"Invalid duration {duration!r}; use e.g. 30s, 1m or 1m30s.")
    hours, minutes, secs = (int(value or 0) for value in parts.groups())
    return hours * 3600 + minutes * 60 + secs


def build_alert_groups(uids, folder_uid, alert_lang, include_lab_rules, link_lang=None):
    """alert_lang sets the texts; link_lang the dashboards the rules link to, which must be a
    language whose dashboards are installed (defaults to alert_lang)."""
    catalog = load_catalog(alert_lang)
    link_lang = link_lang or alert_lang
    bundle = json.loads(ALERT_BUNDLE.read_text(encoding="utf-8"))
    groups = []
    for group in bundle["groups"]:
        rules = []
        for source in group["rules"]:
            if source["uid"] in LAB_ONLY_RULES and not include_lab_rules:
                continue
            rule = localize_uids(rewrite_datasources(copy.deepcopy(source), uids), link_lang)
            # The export repeats the dashboard link (already in the __dashboardUid__/__panelId__
            # annotations) as fields the provisioning API rejects; unlinked rules carry "" and 0.
            rule.pop("dashboardUid", None)
            rule.pop("panelId", None)
            rule["title"] = catalog.get(rule["title"], rule["title"])
            rule["annotations"] = {key: catalog.get(text, text) for key, text in rule.get("annotations", {}).items()}
            rule.update({"folderUID": folder_uid, "ruleGroup": group["name"]})
            rules.append(rule)
        groups.append({**group, "rules": rules})
    return groups


def install_alerts(grafana, folder_uid, groups, interval_override, skipped):
    for group in groups:
        interval = interval_override or group["interval"]
        grafana.call("PUT", f"/api/v1/provisioning/folder/{folder_uid}/rule-groups/{urllib.parse.quote(group['name'])}",
                     {"title": group["name"], "folderUid": folder_uid, "interval": seconds(interval), "rules": group["rules"]})
        print(f"  alert group {group['name']}: {len(group['rules'])} rules, every {interval}")
    if skipped:
        print(f"  lab-only rules left out (pass --include-lab-rules to keep them): {', '.join(sorted(skipped))}")


# --- carousel ----------------------------------------------------------------------------
# The rotation belongs to Application Detail: that dashboard gets a "Carousel" button opening a
# playlist that cycles one pinned copy of it per (server, app). Grafana cannot cycle a variable
# inside one dashboard, so the copies carry the server and app values instead.

def carousel_uid(server, app, lang="en"):
    """Readable prefix plus a hash of the exact (server, app), so 'web.01' and 'web-01', or
    ('a', 'b-c') and ('a-b', 'c'), never share a page. Stays within Grafana's 40 characters."""
    slug = re.sub(r"[^a-z0-9-]+", "-", f"{server}-{app}".lower()).strip("-")[:10].strip("-")
    digest = hashlib.sha1(f"{server}\0{app}".encode()).hexdigest()[:8]
    return f"nginx-carousel-{slug}-{digest}{LANG_SUFFIX[lang]}"


def playlist_name(lang):
    return "Nginx Observability - Carrossel das aplicações" if lang == "pt-BR" else "Nginx Observability - Application carousel"


def owned_playlists(grafana, name):
    """Playlists with this name whose pages are all carousel pages; any other is left alone."""
    owned = []
    for item in grafana.call("GET", f"/api/playlists?name={urllib.parse.quote(name)}") or []:
        if item.get("name") != name:
            continue
        detail = grafana.call("GET", f"/api/playlists/{item['uid']}", allow_404=True) or {}
        pages = detail.get("items") or []
        if all(page.get("value", "").startswith("nginx-carousel-") for page in pages):
            owned.append(item["uid"])
        else:
            print(f"  playlist {name!r} ({item['uid']}) has pages this installer did not create; left alone")
    return owned


def discover_pairs(grafana, prometheus_uid):
    """(server, app) pairs with HTTP traffic in the last day, read through the Grafana datasource."""
    query = urllib.parse.urlencode({"query": "group by (server, app) (max_over_time(nginx_http_response_count_total[1d]))"})
    # A 404 is expected only in a dry run against a Grafana that does not have the datasource yet;
    # in a real run any error stops here with Prometheus's own message.
    answer = grafana.call("GET", f"/api/datasources/proxy/uid/{prometheus_uid}/api/v1/query?{query}",
                          allow_404=grafana.dry_run)
    if answer is None:
        print("  datasource not created yet; the real run discovers the (server, app) pairs")
        return []
    if answer.get("status") != "success":
        raise SystemExit(f"Prometheus query for the carousel failed: {json.dumps(answer)[:300]}")
    pairs = {(item["metric"].get("server", ""), item["metric"].get("app", "")) for item in answer.get("data", {}).get("result", [])}
    return sorted(pair for pair in pairs if all(pair))


def carousel_page(template, server, app, lang="en"):
    page = copy.deepcopy(template)
    page["uid"] = carousel_uid(server, app, lang)
    page["title"] = f"{template['title']} - {app} ({server})"
    page["tags"] = sorted(set(page.get("tags", [])) | {CAROUSEL_TAG})
    page["refresh"] = "30s"
    # Inside the rotation the pages keep the navigation links but not the language switch.
    page["links"] = [link for link in page.get("links", []) if link.get("title") not in LANGUAGES.values()]
    for variable in page.get("templating", {}).get("list", []):
        if variable.get("name") in ("server", "app"):
            value = server if variable["name"] == "server" else app
            variable["current"] = {"selected": True, "text": value, "value": value}
    return page


def carousel_link(playlist_uid, lang):
    pt = lang == "pt-BR"
    return {
        "title": "Carrossel das aplicações" if pt else "Application carousel", "type": "link", "icon": "dashboard",
        "url": f"/playlists/play/{playlist_uid}?kiosk", "includeVars": False, "keepTime": False,
        "targetBlank": False, "asDropdown": False, "tags": [],
        "tooltip": ("Mostra cada aplicação em tela cheia, trocando sozinha; Esc sai do modo quiosque" if pt
                    else "Shows each application full screen in turn; Esc leaves kiosk mode"),
    }


def parse_carousel_apps(text):
    pairs = set()
    for item in (part.strip() for part in text.split(",")):
        server, _, app = item.partition("/")
        if not item:
            continue
        if not server.strip() or not app.strip():
            raise SystemExit(f"--carousel-apps: {item!r} is not server/app")
        pairs.add((server.strip(), app.strip()))
    return sorted(pairs)


def install_carousel(grafana, args, dashboards, uids, lang):
    languages = ["en", "pt-BR"] if lang == "both" else [lang]
    by_uid = {dashboard["uid"]: dashboard for dashboard in dashboards}
    if args.carousel_apps:
        pairs = parse_carousel_apps(args.carousel_apps)
    else:
        pairs = discover_pairs(grafana, uids["prometheus"])
    if not pairs:
        print("  no (server, app) with traffic in the last day; existing pages are kept. "
              "Pass --carousel-apps server/app,... or run again later")
        return
    sub_uid = f"{args.folder_uid}-carousel"
    ensure_folder(grafana, sub_uid, "Carrossel" if "pt-BR" in languages else "Carousel", parent_uid=args.folder_uid)
    wanted = set()
    for language in languages:
        pt = language == "pt-BR"
        detail = by_uid[APP_DETAIL_UID + LANG_SUFFIX[language]]
        for server, app in pairs:
            page = carousel_page(detail, server, app, language)
            wanted.add(page["uid"])
            check_owned_dashboard(grafana, page["uid"], {sub_uid})
            grafana.call("POST", "/api/dashboards/db", {"dashboard": page, "folderUid": sub_uid, "overwrite": True,
                                                        "message": "nginx-observability carousel"})
            print(f"  page {page['title']} ({page['uid']})")
        name = playlist_name(language)
        body = {"name": name, "interval": args.carousel_interval,
                "items": [{"type": "dashboard_by_uid", "value": carousel_uid(server, app, language)} for server, app in pairs]}
        existing = owned_playlists(grafana, name)
        if existing:
            grafana.call("PUT", f"/api/playlists/{existing[0]}", body)
            playlist_uid = existing[0]
            print(f"  {grafana.did('updated', 'would update')} playlist {name}: {len(pairs)} application(s), every {args.carousel_interval}")
        else:
            playlist_uid = grafana.call("POST", "/api/playlists", body).get("uid")
            print(f"  {grafana.did('created', 'would create')} playlist {name}: {len(pairs)} application(s), every {args.carousel_interval}")
        if not playlist_uid:
            print(f"  the carousel button of {detail['title']} is added once the playlist exists")
            continue
        # The only entry point is a button in Application Detail.
        if add_carousel_button(detail, playlist_uid, language):
            grafana.call("POST", "/api/dashboards/db", {"dashboard": detail, "folderUid": args.folder_uid, "overwrite": True,
                                                        "message": "nginx-observability carousel button"})
            print(f"  {grafana.did('added', 'would add')} carousel button to {detail['title']}")
    # Pages for pairs that no longer report traffic are removed, so the rotation stays current.
    for hit in grafana.call("GET", f"/api/search?tag={CAROUSEL_TAG}&type=dash-db") or []:
        if hit.get("uid") not in wanted and hit.get("folderUid") == sub_uid:
            grafana.call("DELETE", f"/api/dashboards/uid/{hit['uid']}")
            print(f"  {grafana.did('removed', 'would remove')} stale page {hit.get('title')} ({hit['uid']})")
    # Playlists of a language not installed in this run, and the names used before the button,
    # would point at deleted pages: remove them (only ones made of carousel pages).
    dropped = [playlist_name(other) for other in ("en", "pt-BR") if other not in languages]
    for name in dropped + ["Nginx Observability - Carousel", "Nginx Observability - Carrossel"]:
        for playlist_uid in owned_playlists(grafana, name):
            grafana.call("DELETE", f"/api/playlists/{playlist_uid}")
            print(f"  {grafana.did('removed', 'would remove')} playlist {name}")


def add_carousel_button(detail, playlist_uid, lang):
    """Put the carousel button on an Application Detail dashboard; False if it was already there."""
    link = carousel_link(playlist_uid, lang)
    links = [item for item in detail.get("links", []) if "/playlists/play/" not in item.get("url", "")]
    changed = link not in detail.get("links", [])
    detail["links"] = links + [link]
    return changed


def keep_carousel_buttons(grafana, dashboards, lang):
    """A run without --carousel must not drop the button of a carousel installed earlier."""
    languages = ["en", "pt-BR"] if lang == "both" else [lang]
    by_uid = {dashboard["uid"]: dashboard for dashboard in dashboards}
    for language in languages:
        existing = owned_playlists(grafana, playlist_name(language))
        if existing:
            add_carousel_button(by_uid[APP_DETAIL_UID + LANG_SUFFIX[language]], existing[0], language)


# --- main --------------------------------------------------------------------------------

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
    parser.add_argument("--lang", choices=["en", "pt-BR", "both"], default="en",
                        help="dashboard language; 'both' installs English and Portuguese with a switch link")
    parser.add_argument("--alert-lang", choices=["en", "pt-BR"],
                        help="language of alert titles and annotations (default: pt-BR when --lang is pt-BR or both)")
    parser.add_argument("--alert-interval", help="evaluation interval for the rule group, e.g. 30s or 1m")
    parser.add_argument("--skip-alerts", action="store_true")
    parser.add_argument("--include-lab-rules", action="store_true",
                        help="also install the rules that watch the lab's health endpoints and exporter")
    parser.add_argument("--carousel", action="store_true",
                        help="add an 'Application carousel' button to Application Detail that rotates one page per (server, app)")
    parser.add_argument("--carousel-interval", default="30s", help="time on each page, e.g. 30s or 1m")
    parser.add_argument("--carousel-apps", help="server/app pairs, comma-separated (default: discovered from traffic)")
    parser.add_argument("--ca-file", help="CA bundle to verify an https Grafana URL signed by an internal CA")
    parser.add_argument("--allow-insecure-http", action="store_true",
                        help="send the token over plain http to a host that is not loopback (not recommended)")
    parser.add_argument("--dry-run", action="store_true", help="read only; print the writes it would make")
    args = parser.parse_args()
    if args.grafana_url.lower().startswith("http://") and not is_loopback(args.grafana_url) and not args.allow_insecure_http:
        raise SystemExit("Refusing to send the token over plain http to a remote Grafana; use https "
                         "(with --ca-file for an internal CA) or run on the Grafana host against 127.0.0.1.")
    if args.alert_interval:
        seconds(args.alert_interval)  # fail before any change
    seconds(args.carousel_interval)
    if hasattr(sys.stdout, "reconfigure"):  # Portuguese titles on consoles that are not UTF-8
        sys.stdout.reconfigure(errors="replace")

    token = os.getenv("GRAFANA_TOKEN")
    if not token:
        raise SystemExit("Set GRAFANA_TOKEN to a service account token with the Admin role.")
    grafana = Grafana(args.grafana_url, token, args.dry_run, args.ca_file)
    health = grafana.call("GET", "/api/health")
    print(f"Grafana {health.get('version')} at {args.grafana_url}{' (dry run: nothing is written)' if args.dry_run else ''}")

    uids = {"prometheus": f"{args.datasource_prefix}-prometheus", "loki": f"{args.datasource_prefix}-loki"}
    print("Datasources")
    ensure_datasource(grafana, "prometheus", uids["prometheus"], "Nginx Observability - Prometheus", args.prometheus_url)
    ensure_datasource(grafana, "loki", uids["loki"], "Nginx Observability - Loki", args.loki_url)
    print("Folder")
    ensure_folder(grafana, args.folder_uid, args.folder_title)
    print(f"Dashboards ({args.lang})")
    dashboards = build_dashboards(args.lang, uids)
    keep_carousel_buttons(grafana, dashboards, args.lang)
    install_dashboards(grafana, args.folder_uid, dashboards)
    if not args.skip_alerts:
        alert_lang = args.alert_lang or ("en" if args.lang == "en" else "pt-BR")
        print(f"Alert rules ({alert_lang})")
        # Rule links open dashboards that exist: the alert language when both are installed,
        # otherwise the only language installed.
        link_lang = alert_lang if args.lang == "both" else args.lang
        groups = build_alert_groups(uids, args.folder_uid, alert_lang, args.include_lab_rules, link_lang)
        skipped = set() if args.include_lab_rules else LAB_ONLY_RULES
        install_alerts(grafana, args.folder_uid, groups, args.alert_interval, skipped)
    if args.carousel:
        print("Carousel")
        install_carousel(grafana, args, dashboards, uids, args.lang)
    print("Done. Route the alerts in the existing notification policies (labels: severity, component, server, app).")


if __name__ == "__main__":
    sys.exit(main())
