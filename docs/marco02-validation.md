# Marco 02 — Evidências de validação

**Data:** 2026-11-12
**Ambiente:** Docker Desktop 29.7.2 / engine Linux, Docker Compose 5.4.0, Grafana 12.3.1, Prometheus 3.8.1, Loki 3.5.7, Alloy 1.12.2, `prometheus-nginxlog-exporter` 1.9.2.
**Origem dos dados:** exclusivamente tráfego sintético dos três serviços locais.

## Recuperação do runtime

Durante a validação, Docker Desktop não estava em execução. `docker context ls` mostrou `desktop-linux` selecionado; `docker version` só retornava a seção cliente, `wsl --list --verbose` mostrava a distro `docker-desktop` como Stopped e `sc query com.docker.service` mostrava o serviço parado. O processo Docker Desktop também não existia. Reabrir o executável já instalado iniciou a distro WSL e restaurou `docker info` com `29.7.2|linux`. Nenhum reset, limpeza, remoção de distribuição, volume ou imagem foi realizado.

Depois da recuperação, `docker compose up -d --build` iniciou os nove serviços. Ao fim, `docker compose ps` mostrou os nove em execução; app-a, app-b, app-c, Nginx e Grafana estavam healthy.

## Consultas exercitadas

O verificador leu os JSON provisionados pela API do Grafana e executou cada expressão de painel diretamente contra as APIs HTTP de Prometheus/Loki, substituindo intervalos e variáveis por valores válidos de teste:

- 30 consultas PromQL aceitas por Prometheus.
- 7 consultas LogQL aceitas por Loki, incluindo seletores de logs, rotas, latência e agregações por IP.
- `nginx_http_response_count_total` foi consultada por cada app, status e método. Cada aplicação apresentou 200, 301, 403, 404, 500, GET e POST.
- `histogram_quantile(0.50|0.95|0.99, sum by (le) (rate(nginx_http_response_time_seconds_hist_bucket{app="<app>"}[5m])))` retornou séries por app.
- `{job="nginx", app="<app>"} | json` retornou eventos JSON e os filtros por app não vazaram para outros streams.
- A consulta de rotas usa campos parseados em tempo de consulta (`path`); origens usam `remote_addr`. Não são labels indexados nem séries Prometheus.
- Grafana retornou os datasources Loki e Prometheus e os dashboards provisionados `nginx-overview`, `nginx-application-detail`, `nginx-live-logs` e `nginx-security`, com 11, 12, 2 e 12 painéis.
- Os quatro caminhos `/d/<uid>/...` retornaram HTTP 200. O destino provisionado `/explore?panes=...`, após interpolação de app e intervalo de exemplo, também retornou HTTP 200.

## Execução final

Comando:

```shell
python tests/verify_pipeline.py --verify-scenarios --verify-persistence
```

Resultado observado:

```text
app-a: status=200,301,403,404,500; methods=GET,POST; p95=0.025s; Loki entries=200
app-b: status=200,301,403,404,500; methods=GET,POST; p95=0.025s; Loki entries=200
app-c: status=200,301,403,404,500; methods=GET,POST; p95=0.025s; Loki entries=200
OK: Prometheus target up, zero exporter parse errors; Grafana sources=Loki,Prometheus, panels={'nginx-overview': 11, 'nginx-application-detail': 12, 'nginx-live-logs': 2, 'nginx-security': 12}, verified panel queries={'prometheus': 30, 'loki': 7}; persistence survived Prometheus/Loki restart
OK: bounded scenarios produced scan_events=107, request increase=91.0
```

O teste executa `degradation`, `scan` e `peak` por 8 segundos cada, taxa máxima configurada em 4 RPS e concorrência 2. Foram observados erros 500 e 109 eventos de caminhos sintéticos de varredura no Loki. Aumento de requisições é medido comparando contadores cumulativos, sem confundir com janela móvel ou tráfego de fundo. A persistência foi verificada reiniciando apenas Prometheus e Loki e consultando novamente o contador e o evento identificado.

## Limitações de evidência

O acesso ao host de navegador do Computer Use não estava disponível nesta execução; por isso não há capturas de tela. As evidências são resultados das APIs reais, dos containers e do script de integração, sem imagens simuladas. O script confirma que a URL de Explore está provisionada, mas a ativação visual do Live tail WebSocket não pôde ser capturada nesta sessão.

## Incidentes e correções de integração

- O cenário `HTTP methods` foi baseado na métrica Prometheus `method`, evitando uma expressão LogQL de agregação inválida.
- O padrão de caminhos de scanner usava escapes incompatíveis com LogQL; os escapes foram duplicados de acordo com a sintaxe validada na API Loki.
- A chamada `docker compose run` passou a incluir `python -u generate.py`, pois argumentos após o serviço substituem o comando configurado no Compose.
- A aplicação simulada agora separa o path da query string, permitindo marcadores de teste sem devolver 404 ao caminho raiz.
- O teste de persistência marca a requisição na query string e localiza o campo `request` no evento JSON; o campo `path` usa `$uri` e corretamente não inclui query parameters.
- O comparativo de tráfego dos cenários usa o contador cumulativo, e o teste espera explicitamente que o scrape tenha visto os status e métodos em cada app.
