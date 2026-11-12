# Marco 02.3 - Live Logs

## Implemented behavior

- The HTTP access panel is a native Grafana table with Time, App, Method, Status, Path, Duration (ms), and Source IP.
- Grafana parses the original JSON event line for display fields while hiding that line from the compact table. The complete event remains available in the Loki data source and Explore.
- Status cells use native threshold coloring: 4xx is orange and 5xx is red.
- The Loki range query is capped at 500 records, paginated, and sorted by Time descending (newest first).
- Application, Method, Status, Path, and Source IP regex descriptions are provided. Path and Source IP are Loki event filters only; the IP is not promoted to an indexed label.
- The Explore dashboard link carries all five current filters and the selected time range. Users click Grafana Explore's native Live control to start tailing.
- The dashboard's 2-second refresh is periodic refresh after ingestion; it is not a WebSocket stream.

## Validation evidence

Executed:

```text
python tests/verify_pipeline.py --verify-scenarios --verify-persistence
```

The run passed for all three applications and after Prometheus/Loki restart. Relevant output:

```text
Live Logs checks={'filters': {'Application': 200, 'Method': 200, 'Status': 62, 'Path': 11, 'Source IP': 77, 'Combined': 5}, 'grafana_frames': 1, 'events': 500, 'max_lines': 500, 'explore_filters': 5}, Grafana Live websocket=HTTP/1.1 101 Switching Protocols; persistence survived Prometheus/Loki restart
OK: bounded scenarios produced scan_events=42, request increase=85.0; no-traffic zero checks=3
```

The test also validated all provisioned dashboard PromQL/LogQL queries, the Overview application categories, and the Application Detail assertions. `docker compose config --quiet`, dashboard JSON parsing, Python compilation, and `git diff --check` passed.

Grafana returned up to the configured 500 recent events through the Loki data source API. Each filter was run independently against ingested events; the combined app-a/GET/403/path/source-IP query returned only matching events. A separate app-b query contained only app-b records. The Explore URL was decoded in the test and checked for every filter placeholder and the dashboard's `$__from`/`$__to` range.

The WebSocket handshake to Grafana Live's `/api/live/ws` returned HTTP 101 with a valid `Sec-WebSocket-Accept`. This verifies the native WebSocket endpoint is available. It does not prove the Explore interface's Live subscription or rendered stream, because the browser-control host was unavailable. No visual validation is claimed.

## Environment note

After editing the bind-mounted JSON, Grafana continued serving its previous provisioned dashboard even though the container saw the new file. Restarting only the Grafana service loaded the updated dashboard. No other service was restarted for this reload, and no volume or image was removed.
