# Marco 02.4 - Security dashboard

## Audit findings

- The HTTP Methods panel used an instant Prometheus `increase()` query but did not convert returned series to rows or select the series name as its bar category. Grafana rendered a timestamp-like category instead of GET/POST.
- Scanner-like path detections already queried the expected path patterns, but the dashboard did not explain how to interpret an empty result separately from a datasource query error.
- The origin query grouped by source IP only and counted every matching event, while the title implied recurrence. The source IP filter was not consistently combined with the selected application.
- Recent security events queried Loki in instant mode and exposed technical Loki frame fields instead of parsed HTTP event fields.
- Request-rate panels had no explicit precision for sub-1 req/s values, and overview indicators did not consistently identify current rates, period estimates, and collection health.
- Dashboard panels were flat and lacked an Explore link that preserved the security filters and time range.

## Changes

- Added native Grafana rows for **Overview**, **Suspicious Activity**, and **Investigation**.
- HTTP Methods now applies `seriesToRows`, uses `Metric` as its category, labels values as a period estimate, and displays whole requests. GET and POST are checked against live Prometheus frames.
- Scanner-like paths use the existing synthetic path patterns and structured metadata in Loki. The description distinguishes no matching events from query errors and states that observed patterns do not prove an attack.
- Origin ranking now requires at least two 4xx/5xx events in five minutes, groups results by app and `remote_addr`, honors both app and source-IP filters, and limits display to the top ten. IP remains structured event metadata; it is not indexed or persisted as a Prometheus label.
- Recent security events use a range query and a structured table with Time, App, Status, Method, Path, Source IP, and Duration (ms), newest first and capped at 500 rows. The original JSON remains in Loki/Explore. Status cells use native thresholds for 4xx/5xx.
- Current rate panels retain three decimal places and have no fixed minimum or maximum. The 429 indicator is an estimated selected-period total; exporter parse errors are labeled separately as collection health.
- Added an Explore link carrying the current application, source IP regex, security status filter, and dashboard time range.

## Validation

Executed:

```text
python tests/verify_pipeline.py --verify-scenarios --verify-persistence
```

The full test passed. It checked the Overview, Application Detail, Live Logs, and Security dashboard queries, then ran bounded degradation, scan, and peak scenarios. The scan generated 31 matching events in the isolated scenario interval; the run observed an increase of 84 requests and passed idle-window checks. Prometheus and Loki data remained available after their restart.

A security-specific check over the recent five-minute Loki range returned 34 scanner-like events across app-a/app-b/app-c and six repeated-error app/origin pairs. A source-IP-only filter returned three origins; combining app-a with the source-IP filter returned one origin and six recent app-a events. The test asserts matching path and error statuses, correlates scan origins to repeated errors, and verifies application isolation.

`docker compose config --quiet`, dashboard JSON parsing, Python compilation, and `git diff --check` passed. The Grafana API confirmed 15 Security panels, including the three section rows. Rate panel PromQL was queried against Prometheus; the dashboard's LogQL was queried against Loki. The HTTP methods query returned GET and POST.

Visual validation was unavailable: the computer-use host reported that no browser was available. Therefore no screenshot or claim of rendered visual confirmation is included. API, query, and dashboard-configuration checks passed, but the Grafana page should receive a visual review when a browser is available.

## Scope

Only the local Compose laboratory was used. No corporate servers, production data, external IP lookups, or blocking integrations were involved. No architecture or data collection changes were made.
