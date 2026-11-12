"""Build deterministic, provisioned Grafana dashboard JSON for the lab."""
import json
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "config" / "grafana" / "dashboards"
PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}
INCREASE_NOTE = "Estimated with Prometheus increase(), which extrapolates counter samples to the selected interval. Displayed rounded to whole requests; this is not an exact event count."


def app_variable():
    return {
        "name": "app", "label": "Application", "type": "query", "datasource": PROM,
        "query": {"query": "label_values(nginx_http_response_count_total, app)", "refId": "Prometheus-app"},
        "refresh": 2, "includeAll": True, "allValue": ".*", "multi": False,
        "current": {"selected": True, "text": "All", "value": "$__all"},
    }


def custom_variable(name, label, options):
    options = list(options)
    if options and options[0] == "All : .*":
        options.pop(0)
    parsed = []
    for option in options:
        if " : " in option:
            text, value = option.split(" : ", 1)
        else:
            text = value = option
        parsed.append({"selected": False, "text": text, "value": value})
    parsed[0]["selected"] = True
    return {
        "name": name, "label": label, "type": "custom", "query": ",".join(options),
        "includeAll": True, "allValue": ".*", "multi": False,
        "current": {"selected": True, "text": "All", "value": "$__all"},
        "options": parsed,
    }


def textbox_variable(name, label, value):
    return {"name": name, "label": label, "type": "textbox", "query": value,
            "current": {"selected": True, "text": value, "value": value}}


def prom_target(expr, ref_id="A", legend=None, instant=False):
    target = {"datasource": PROM, "editorMode": "code", "expr": expr, "refId": ref_id, "instant": instant}
    if legend:
        target["legendFormat"] = legend
    return target


def loki_target(expr, ref_id="A", legend=None, instant=False, max_lines=None):
    target = {"datasource": LOKI, "editorMode": "code", "expr": expr,
              "queryType": "instant" if instant else "range", "refId": ref_id}
    if legend:
        target["legendFormat"] = legend
    if max_lines is not None:
        target["maxLines"] = max_lines
    return target


def panel(panel_id, title, panel_type, x, y, w, h, targets, unit=None, description=None,
          options=None, thresholds=None, overrides=None, no_value=None, transformations=None):
    defaults = {"color": {"mode": "palette-classic"}, "mappings": []}
    if unit:
        defaults["unit"] = unit
    if no_value:
        defaults["noValue"] = no_value
    if thresholds:
        defaults["thresholds"] = {"mode": "absolute", "steps": thresholds}
    result = {
        "id": panel_id, "title": title, "type": panel_type,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "datasource": targets[0]["datasource"], "targets": targets,
        "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
        "options": options or {},
    }
    if description:
        result["description"] = description
    if transformations:
        result["transformations"] = transformations
    return result


def stat(panel_id, title, expr, x, color="green", unit=None, description=None, y=0, w=4, h=5,
         decimals=None, legend=None, instant=False, text_mode="value", orientation="auto"):
    thresholds = [{"color": color, "value": None}]
    result = panel(panel_id, title, "stat", x, y, w, h,
                 [prom_target(expr, legend=legend, instant=instant)], unit, description,
                 {"colorMode": "value", "graphMode": "area", "justifyMode": "center",
                  "orientation": orientation, "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                  "showPercentChange": False, "textMode": text_mode}, thresholds=thresholds,
                 no_value="No samples in selected range")
    if decimals is not None:
        result["fieldConfig"]["defaults"]["decimals"] = decimals
    return result


def series_panel(panel_id, title, expr, x, y, w, h, unit=None, legend="{{app}}", description=None,
                 overrides=None):
    options = {"legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": True},
               "tooltip": {"mode": "multi", "sort": "desc"}}
    return panel(panel_id, title, "timeseries", x, y, w, h,
                 [prom_target(expr, legend=legend)], unit, description, options, overrides=overrides)


def bar_panel(panel_id, title, expr, x, y, w, h, datasource=LOKI, legend="{{path}}", description=None,
              category_field=None, decimals=None, sort_descending=False):
    target = loki_target(expr, instant=True, legend=legend) if datasource == LOKI else prom_target(expr, legend=legend, instant=True)
    options = {"orientation": "horizontal", "showValue": "always", "stacking": "none",
               "legend": {"displayMode": "hidden", "placement": "bottom", "showLegend": False},
               "tooltip": {"mode": "single", "sort": "desc"}}
    if category_field:
        options["xField"] = category_field
    result = panel(panel_id, title, "barchart", x, y, w, h, [target], "short", description, options)
    if category_field:
        # Explicit instant-vector series names become one Metric row per series;
        # this avoids treating the 2026 Time field as the app category.
        result["transformations"] = [{"id": "seriesToRows", "options": {}}]
        if sort_descending:
            result["transformations"].append({"id": "sortBy", "options": {"sort": [{"field": "Value", "desc": True}]}})
    if decimals is not None:
        result["fieldConfig"]["defaults"]["decimals"] = decimals
    return result


def table_panel(panel_id, title, expr, x, y, w, h, datasource=LOKI, description=None,
                transformations=None, unit=None, decimals=None, overrides=None, sort_by=None, legend=None):
    target = loki_target(expr, instant=True, legend=legend) if datasource == LOKI else prom_target(expr, instant=True, legend=legend)
    options = {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}}
    if sort_by:
        options["sortBy"] = [{"displayName": sort_by, "desc": True}]
    result = panel(panel_id, title, "table", x, y, w, h, [target], unit, description,
                   options=options, overrides=overrides, transformations=transformations)
    if decimals is not None:
        result["fieldConfig"]["defaults"]["decimals"] = decimals
    return result


def dashboard_links():
    targets = [
        ("Overview", "nginx-overview/overview"),
        ("Application Detail", "nginx-application-detail/application-detail"),
        ("Live Logs", "nginx-live-logs/live-logs"),
        ("Security", "nginx-security/security"),
    ]
    return [{"title": title, "type": "link", "url": f"/d/{path}", "icon": "external link",
             "tooltip": f"Open {title} with the current app and time range",
             "includeVars": True, "keepTime": True, "targetBlank": False}
            for title, path in targets]


def explore_link():
    panes = {"0": {
        "datasource": "loki",
        "queries": [{"refId": "A", "datasource": {"type": "loki", "uid": "loki"},
                      "expr": '{job="nginx", app=~"__APP__"}'}],
        "range": {"from": "__FROM__", "to": "__TO__"},
    }}
    encoded = quote(json.dumps(panes, separators=(",", ":")), safe="")
    encoded = encoded.replace("__APP__", "$app").replace("__FROM__", "$__from").replace("__TO__", "$__to")
    return f"/explore?panes={encoded}&schemaVersion=1&orgId=1"


def base_dashboard(uid, title, description, refresh, variables, panels):
    return {
        "id": None, "uid": uid, "title": title, "description": description,
        "tags": ["nginx", "observability"], "timezone": "browser", "schemaVersion": 41,
        "version": 1, "refresh": refresh, "time": {"from": "now-15m", "to": "now"},
        "links": dashboard_links(), "templating": {"list": variables}, "panels": panels,
        "annotations": {"list": [{"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                                   "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)",
                                   "name": "Annotations & Alerts", "type": "dashboard"}]},
        "graphTooltip": 1, "fiscalYearStartMonth": 0, "liveNow": False,
    }


def overview():
    steps = [
        stat(1, "Current request rate", 'sum(rate(nginx_http_response_count_total{app=~"$app"}[$__rate_interval]))', 0, "blue", "reqps", y=0, w=4, h=4),
        stat(2, "Requests in selected period", 'sum(increase(nginx_http_response_count_total{app=~"$app"}[$__range])) or vector(0)', 4, "blue", "short", INCREASE_NOTE, y=0, w=4, h=4, decimals=0),
        stat(3, "Current 4xx rate", 'sum(rate(nginx_http_response_count_total{app=~"$app",status=~"4.."}[$__rate_interval])) or vector(0)', 8, "orange", "reqps", y=0, w=4, h=4),
        stat(4, "4xx responses (period)", 'sum(increase(nginx_http_response_count_total{app=~"$app",status=~"4.."}[$__range])) or vector(0)', 12, "orange", "short", INCREASE_NOTE, y=0, w=3, h=4, decimals=0),
        stat(5, "Current 5xx rate", 'sum(rate(nginx_http_response_count_total{app=~"$app",status=~"5.."}[$__rate_interval])) or vector(0)', 15, "red", "reqps", y=0, w=3, h=4),
        stat(6, "5xx responses (period)", 'sum(increase(nginx_http_response_count_total{app=~"$app",status=~"5.."}[$__range])) or vector(0)', 18, "red", "short", INCREASE_NOTE, y=0, w=3, h=4, decimals=0),
        stat(12, "P95 latency", f'histogram_quantile(0.95,sum by (le) (rate(nginx_http_response_time_seconds_hist_bucket{{app=~"$app"}}[$__rate_interval])))', 21, "green", "s", y=0, w=3, h=4),
    ]
    panels = steps + [
        series_panel(7, "Traffic by status (rate)", 'sum by (status) (rate(nginx_http_response_count_total{app=~"$app"}[$__rate_interval]))', 0, 4, 12, 8, "reqps", "{{status}}", overrides=[
            {"matcher": {"id": "byRegexp", "options": "2.."}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "green"}}]},
            {"matcher": {"id": "byRegexp", "options": "3.."}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "yellow"}}]},
            {"matcher": {"id": "byRegexp", "options": "4.."}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "orange"}}]},
            {"matcher": {"id": "byRegexp", "options": "5.."}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]},
        ]),
        bar_panel(8, "Requests by application (period total)", 'sum by (app) (increase(nginx_http_response_count_total{app=~"$app"}[$__range]))', 12, 4, 12, 8, PROM, "{{app}}", INCREASE_NOTE, category_field="Metric", decimals=0),
        series_panel(9, "P95 by application", 'histogram_quantile(0.95,sum by (app,le) (rate(nginx_http_response_time_seconds_hist_bucket{app=~"$app"}[$__rate_interval])))', 0, 12, 12, 8, "s", "{{app}}"),
        series_panel(10, "Error rate over time by application", 'sum by (app) (rate(nginx_http_response_count_total{app=~"$app",status=~"4..|5.."}[$__rate_interval]))', 12, 12, 12, 8, "reqps", "{{app}}"),
        bar_panel(11, "Applications with the most errors (period total)", 'topk(3, sum by (app) (increase(nginx_http_response_count_total{app=~"$app",status=~"4..|5.."}[$__range])) or on (app) (0 * sum by (app) (nginx_http_response_count_total{app=~"$app"})))', 0, 20, 24, 5, PROM, "{{app}}", INCREASE_NOTE, category_field="Metric", decimals=0),
    ]
    return base_dashboard("nginx-overview", "Nginx | Overview", "Traffic, reliability, latency, and cross-application comparison.", "10s", [app_variable()], panels)


def application_detail():
    app = 'app=~"$app"'
    metric_filters = f'{app},method=~"${{method:regex}}",status=~"${{status:raw}}"'
    # Alloy stores these parsed fields as structured metadata, so filters avoid reparsing
    # every JSON key and keep metric queries within Loki's per-query series limit.
    event_filter = ' | method=~"${method:regex}" | status=~"${status:raw}" | path=~".*${path:regex}.*"'
    panel_vars = [app_variable(), custom_variable("method", "Method", ["All : .*", "GET", "POST"]),
                  custom_variable("status", "Status class / code", ["All : .*", "2xx : 2..", "3xx : 3..", "4xx : 4..", "5xx : 5..", "403", "404", "429", "500"]),
                  textbox_variable("path", "Path contains (Loki only)", "")]
    panels = [
        stat(1, "Requests / second", f"sum(rate(nginx_http_response_count_total{{{metric_filters}}}[$__rate_interval]))", 0, "blue", "reqps"),
        stat(2, "Requests in range", f"sum(increase(nginx_http_response_count_total{{{metric_filters}}}[$__range])) or vector(0)", 4, "blue", "short"),
        stat(3, "P50 latency", f'histogram_quantile(0.50,sum by (le,app) (rate(nginx_http_response_time_seconds_hist_bucket{{{metric_filters}}}[$__rate_interval])))', 8, "green", "s", legend="{{app}}", instant=True, text_mode="value_and_name", orientation="horizontal"),
        stat(4, "P95 latency", f'histogram_quantile(0.95,sum by (le,app) (rate(nginx_http_response_time_seconds_hist_bucket{{{metric_filters}}}[$__rate_interval])))', 12, "yellow", "s", legend="{{app}}", instant=True, text_mode="value_and_name", orientation="horizontal"),
        stat(5, "P99 latency", f'histogram_quantile(0.99,sum by (le,app) (rate(nginx_http_response_time_seconds_hist_bucket{{{metric_filters}}}[$__rate_interval])))', 16, "orange", "s", legend="{{app}}", instant=True, text_mode="value_and_name", orientation="horizontal"),
        stat(6, "429 responses", f'sum(increase(nginx_http_response_count_total{{{metric_filters},status="429"}}[$__range])) or vector(0)', 20, "orange", "short", "No 429s are synthesized by the current Nginx demo."),
        series_panel(7, "Request rate by HTTP status", f'sum by (status) (rate(nginx_http_response_count_total{{{metric_filters}}}[$__rate_interval]))', 0, 5, 12, 8, "reqps", "{{status}}"),
        series_panel(8, "4xx and 5xx over time", f'sum by (status) (rate(nginx_http_response_count_total{{{metric_filters},status=~"4..|5.."}}[$__rate_interval]))', 12, 5, 12, 8, "reqps", "{{status}}"),
        bar_panel(9, "Methods (estimated period total)", f'sum by (method) (increase(nginx_http_response_count_total{{{metric_filters}}}[$__range]))', 0, 13, 8, 8, PROM, "{{method}}", INCREASE_NOTE, category_field="Metric", decimals=0),
        bar_panel(10, "Most requested paths (event count)", f'topk(10,sum by (path) (count_over_time({{job="nginx",app=~"$app"}}{event_filter} [$__range])))', 8, 13, 8, 8, LOKI, "{{path}}", "Exact Loki event count in the selected period. Top 10 paths, ordered by request volume; app, method, status, and path filters apply. Path is structured metadata, not an indexed stream label.", category_field="Metric", decimals=0, sort_descending=True),
        table_panel(11, "Slowest by app/method/status/path", f'topk(10,1000 * max by (app,method,status,path) (max_over_time({{job="nginx",app=~"$app"}}{event_filter} | unwrap request_time | __error__="" [$__range])))', 16, 13, 8, 8, LOKI, "Maximum request time in milliseconds for each app, method, status, and path group within the selected range. Results are limited to the top 10 and sorted by duration descending.", unit="ms", decimals=0, legend="{{app}} / {{method}} / {{status}} / {{path}}", sort_by="Max duration (ms)", transformations=[
            {"id": "seriesToRows", "options": {}},
            {"id": "sortBy", "options": {"sort": [{"field": "Value", "desc": True}]}},
            {"id": "organize", "options": {
                "renameByName": {"Metric": "App / Method / Status / Path", "Value": "Max duration (ms)"},
            }},
        ]),
        panel(12, "Recent requests for selected app", "table", 0, 21, 24, 11,
              [loki_target(f'{{job="nginx",app=~"$app"}}{event_filter}', max_lines=100)],
              description="Shows Time, App, Method, Status, Path, Duration (ms), and Source IP. Other fields and the full JSON line remain available in Loki/Explore.",
              options={"showHeader": True, "cellHeight": "sm", "footer": {"show": False, "enablePagination": True},
                       "sortBy": [{"displayName": "Time", "desc": True}]},
              overrides=[{"matcher": {"id": "byName", "options": "Duration (ms)"},
                           "properties": [{"id": "unit", "value": "ms"}, {"id": "decimals", "value": 0}]}],
              transformations=[
                  {"id": "extractFields", "options": {"source": "Line", "format": "json", "replace": False}},
                  {"id": "convertFieldType", "options": {"conversions": [{"targetField": "request_time", "destinationType": "number"}], "fields": {}}},
                  {"id": "calculateField", "options": {"mode": "binary", "binary": {
                      "left": {"matcher": {"id": "byName", "options": "request_time"}},
                      "operator": "*", "right": {"fixed": "1000"}}, "alias": "Duration (ms)", "replaceFields": False}},
                  {"id": "organize", "options": {
                      "excludeByName": {"labels": True, "tsNs": True, "labelTypes": True, "id": True,
                                         "request_time": True, "Line": True},
                      "indexByName": {"Time": 0, "app": 1, "method": 2, "status": 3, "path": 4,
                                      "Duration (ms)": 5, "remote_addr": 6},
                      "renameByName": {"app": "App", "method": "Method", "status": "Status",
                                       "path": "Path", "remote_addr": "Source IP"},
                  }},
              ]),
    ]
    return base_dashboard("nginx-application-detail", "Nginx | Application Detail", "Application, Method, and Status filter metrics and logs. Path filters Loki panels only because paths are not Prometheus labels.", "10s", panel_vars, panels)


def live_logs():
    variables = [app_variable(), custom_variable("method", "Method", ["All : .*", "GET", "POST"]),
                 custom_variable("status", "Status class / code", ["All : .*", "2xx : 2..", "3xx : 3..", "4xx : 4..", "5xx : 5..", "403", "404", "429", "500"]),
                 textbox_variable("path", "Path contains", ""), textbox_variable("source_ip", "Source IP regex", ".*")]
    text = panel(1, "Live tail", "text", 0, 0, 24, 4, [prom_target("vector(1)")],
                description="Dashboard logs refresh every 2 seconds; this is not streaming. Open the Explore link above and click Live for Loki websocket tail.",
                options={"mode": "markdown", "content": "**Dashboard refresh:** up to 2s after ingestion. **Live tail:** use the Explore link in this dashboard, then click **Live** in Grafana Explore. Explore provides the native Loki websocket stream."})
    logs = panel(2, "HTTP access events", "logs", 0, 4, 24, 20,
                 [loki_target('{job="nginx",app=~"$app"} | json | method=~"${method:regex}" | status=~"${status:raw}" | path=~".*${path:regex}.*" | remote_addr=~"${source_ip:raw}"')],
                 description="The line remains the original JSON event; expand a row for parsed fields. IP is an event field, not an indexed label.",
                 options={"showTime": True, "showLabels": True, "showCommonLabels": False, "wrapLogMessage": True,
                          "prettifyLogMessage": True, "enableLogDetails": True, "sortOrder": "Descending", "maxLines": 500})
    dashboard = base_dashboard("nginx-live-logs", "Nginx | Live Logs", "Filter recent HTTP access events; use Grafana Explore Live for websocket tailing.", "2s", variables, [text, logs])
    dashboard["links"].append({"title": "Open Loki Explore Live tail", "type": "link", "url": explore_link(),
                               "icon": "external link", "tooltip": "Open the matching app and time range in Explore, then click Live.",
                               "includeVars": False, "keepTime": False, "targetBlank": False})
    return dashboard


def security():
    variables = [app_variable(), textbox_variable("source_ip", "Source IP regex", ".*")]
    app_stream = '{job="nginx",app=~"$app"} | json'
    panels = [
        stat(1, "403 / second", 'sum(rate(nginx_http_response_count_total{app=~"$app",status="403"}[$__rate_interval]))', 0, "orange", "reqps"),
        stat(2, "404 / second", 'sum(rate(nginx_http_response_count_total{app=~"$app",status="404"}[$__rate_interval]))', 4, "yellow", "reqps"),
        stat(3, "429 in range", 'sum(increase(nginx_http_response_count_total{app=~"$app",status="429"}[$__range])) or vector(0)', 8, "orange", "short", "No 429s are generated unless a future Nginx policy produces them."),
        stat(4, "5xx / second", 'sum(rate(nginx_http_response_count_total{app=~"$app",status=~"5.."}[$__rate_interval]))', 12, "red", "reqps"),
        stat(5, "Requests / second", 'sum(rate(nginx_http_response_count_total{app=~"$app"}[$__rate_interval]))', 16, "blue", "reqps"),
        stat(6, "Exporter parse errors", 'sum(nginx_parse_errors_total{app=~"$app"}) or vector(0)', 20, "green", "short"),
        series_panel(7, "403 / 404 / 429 trends", 'sum by (status,app) (rate(nginx_http_response_count_total{app=~"$app",status=~"403|404|429"}[$__rate_interval]))', 0, 5, 12, 8, "reqps", "{{app}} / {{status}}", "Anomalies are signals for investigation; isolated 404s are not classified as attacks."),
        bar_panel(8, "HTTP methods", 'sum by (method) (increase(nginx_http_response_count_total{app=~"$app"}[$__range]))', 12, 5, 12, 8, PROM, "{{method}}"),
        bar_panel(9, "Common scanner-like paths (observed)", f'sum by (app,path) (count_over_time({app_stream} | path=~".*(\\\\.env|\\\\.git|wp-admin|wp-login\\\\.php|phpmyadmin|/etc/passwd).*" [5m]))', 0, 13, 12, 9, LOKI, "{{app}} {{path}}", "Finite synthetic probes only; these paths indicate a pattern worth checking, not proof of malicious intent."),
        bar_panel(10, "Origins with repeated 4xx / 5xx", f'topk(10,sum by (remote_addr) (count_over_time({app_stream} | status=~"4..|5.." | remote_addr=~"${{source_ip:raw}}" [5m])))', 12, 13, 12, 9, LOKI, "{{remote_addr}}", "The source is the synthetic traffic-generator container in this lab. IP remains parsed event metadata, never a Loki stream or Prometheus label."),
        series_panel(11, "Error concentration by application", 'sum by (app) (rate(nginx_http_response_count_total{app=~"$app",status=~"4..|5.."}[$__rate_interval]))', 0, 22, 12, 8, "reqps", "{{app}}"),
        table_panel(12, "Recent 403 / 404 / 5xx events", f'{app_stream} | status=~"403|404|5.." | remote_addr=~"${{source_ip:raw}}"', 12, 22, 12, 8, LOKI, "Inspect the original event and time before drawing conclusions."),
    ]
    return base_dashboard("nginx-security", "Nginx | Security", "Synthetic indicators for triage; unusual traffic is not automatically classified as an attack.", "10s", variables, panels)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    dashboards = [overview(), application_detail(), live_logs(), security()]
    for dashboard in dashboards:
        path = OUTPUT / f"{dashboard['uid']}.json"
        path.write_text(json.dumps(dashboard, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")
    legacy = OUTPUT / "nginx-observability.json"
    if legacy.exists():
        legacy.unlink()


if __name__ == "__main__":
    main()
