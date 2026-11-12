# Auditoria técnica — Dashboards do Marco 02

**Data:** 2026-11-11
**Ambiente consultado:** Grafana 12.3.1, Prometheus 3.8.1, Loki 3.5.7, exporter `prometheus-nginxlog-exporter` 1.9.2.
**Dados:** exclusivamente tráfego sintético do laboratório local.

## Estado atual observado

- A stack Compose contém nove serviços. As aplicações `app-a`, `app-b` e `app-c`, Nginx, exporter, Alloy, Loki, Prometheus, Grafana e gerador estão ativos. `/api/health` do Grafana retornou `database=ok`, versão `12.3.1`.
- O dashboard provisionado `nginx-observability` está carregado no Grafana (`provisioned=true`) e contém cinco painéis: requisições/s, total em 15 minutos, respostas por status, P95 e logs. Seu seletor `$app` vem de `label_values(nginx_http_response_count_total, app)` e contempla `All`.
- A família de métricas observada no Prometheus inclui `nginx_http_response_count_total`, `nginx_http_response_time_seconds`, `nginx_http_response_time_seconds_hist_bucket`, `_count`, `_sum`, `nginx_http_response_size_bytes` e `nginx_parse_errors_total`. Também existem métricas internas Go/process e `up`.
- Séries reais de `nginx_http_response_count_total` têm labels `app`, `method`, `status`, `instance` e `job`. Nos histogramas estão ainda `le`. `app` tem somente três valores estáveis. `method` observado neste momento é apenas `GET`; o gerador e as aplicações ainda não produzem variedade de métodos.
- O exporter separa por namespace/file de app e aplica o mesmo prefixo `nginx`, com o namespace exposto como label `app`. O contador de erros de parse está em zero para os três apps.
- Os labels de stream visíveis na API Loki são `app`, `filename`, `job` e `service_name`. O Alloy extrai `time`, `method`, `path`, `status`, `request_time` e `remote_addr` do JSON; método, caminho, status, tempo e IP são structured metadata/campos, não labels indexados. O conteúdo de linha também conserva `app`, `remote_user`, `body_bytes_sent`, `http_referer` e `http_user_agent`.
- A consulta por stream `{job="nginx", app="app-a"}` retorna logs recentes. O teste de Marco 01 já valida os campos JSON para cada aplicação.
- O Loki só indexa labels; variáveis do datasource Loki podem enumerar labels e valores indexados, mas não descobrem valores que existam somente em JSON/structured metadata. Portanto método/status serão filtros fixos com opções restritas ao laboratório ou campos de busca, não novos labels Loki de alta cardinalidade.

## Consultas confirmadas no runtime

Consulta PromQL instantânea executada via `promtool`:

```promql
nginx_http_response_count_total
```

Ela retornou séries distintas por `app`, método e status, por exemplo `app-a / GET / 200`, `app-a / GET / 301` e `app-a / GET / 500`. Foram observados 403/404/500 também em `app-b` e `app-c`. `nginx_parse_errors_total` retornou zero em cada app. Os histogramas clássicos contêm buckets de `0.005` até `5` segundos e `+Inf`.

Consulta LogQL usada no verificador integrado:

```logql
{job="nginx", app="app-a"}
```

O verificador também decodifica as linhas JSON e exige timestamp, app, método, caminho, status, tempo de resposta e IP.

## Referências de dashboards

| Referência | Organização e adequação | Compatibilidade, manutenção e licença |
|---|---|---|
| [25257 — Nginx Log Exporter Dashboard](https://grafana.com/grafana/dashboards/25257-nginx-log-exporter-dashboard/) | Foco relevante em tráfego, latência, confiabilidade, rotas e saúde do parser. A revisão pública descreve painéis stat, séries temporais, heatmap, tabela e barras, úteis para operação e investigação. | O JSON oficial foi inspecionado: ele usa a mesma família `nginx_http_response_count_total` e inclui tráfego, taxa de erros, latência, rotas e erros de parse. Porém declara requisito Grafana `13.1.0`, acima do laboratório `12.3.1`, possui aproximadamente 40 painéis em uma página longa e variáveis de datasource/job, sem seleção `$app`. A página não informa licença explícita para o JSON comunitário; não importar nem copiar painéis sem uma licença clara. Reutilizar conceitos e consultas compatíveis, com atribuição à referência. Publicado por `rohitpotato`, atualizado em 2026-05-06. |
| [17452 — NGINX Prometheus exporter](https://grafana.com/grafana/dashboards/17452-nginx/) | Dashboard para estatísticas agregadas do exporter nginxinc; útil para conexões e `stub_status`, com séries e indicadores do NGINX. | A fonte oficial é o JSON do repositório `nginx/nginx-prometheus-exporter`. Esta stack não executa esse exporter e não possui suas séries `nginx_connections_*`; importá-lo produziria painéis vazios. Não acrescentar outro exporter apenas para reutilizar o dashboard. A atribuição e licença devem acompanhar qualquer adaptação de código do repositório fonte. |

Referências de produto consultadas: [dashboards Grafana](https://grafana.com/docs/grafana/latest/dashboards/), [datasource Loki](https://grafana.com/docs/grafana/latest/datasources/loki/), [variáveis Loki e limite de labels indexados](https://grafana.com/docs/grafana/latest/datasources/loki/template-variables/), [LogQL](https://grafana.com/docs/loki/latest/query/), [Live tail no Explore](https://grafana.com/docs/grafana/latest/datasources/loki/query-editor/) e [fundamentos PromQL](https://prometheus.io/docs/prometheus/latest/querying/basics/).

Grafana Explore com Loki oferece Live tail por WebSocket. Refresh de dashboard/painel a cada poucos segundos só reconsulta o intervalo selecionado e não equivale a Live tail. Links de dashboard, painel e dados podem carregar variáveis e intervalo temporal, segundo a [documentação de links](https://grafana.com/docs/grafana/latest/visualizations/dashboards/build-dashboards/manage-dashboard-links/).

## Lacunas priorizadas

1. Substituir o dashboard genérico atual por Overview, Application Detail, Live Logs e Security com consultas validadas às séries e campos existentes.
2. Adicionar links preservando `$app` e intervalo; criar caminho explícito do dashboard de logs para Explore e explicar que Live tail é ativado no Explore.
3. Ampliar o simulador com métodos POST e rotas suspeitas que gerem 404 reais; fornecer cenários limitados em taxa, concorrência e duração. Não rotular 404 como ataque.
4. Derivar tendências por rota e origem com consultas Loki sobre JSON em janelas curtas, mantendo caminho e IP fora dos labels indexados e das séries Prometheus.
5. Exibir 429 somente quando houver evento real; hoje a aplicação não gera esse status e Nginx não aplica rate limit.

**Decisão de reutilização:** manter Grafana, Prometheus, Loki, Alloy e o exporter existentes. Usar as consultas e a cobertura de operação do 25257 como referência, mas criar JSON de dashboard próprio compatível com Grafana 12.3.1 e com label `$app`; não importar o dashboard nginxinc 17452 porque suas métricas não estão instaladas.

## Resultado após implementação

As cinco lacunas foram tratadas com quatro dashboards provisionados e seleção dinâmica por `$app`; filtros de método/status/path/IP foram implementados com variáveis Grafana, sem promover campos de alta cardinalidade a labels; o gerador passou a emitir GET e POST e cenários finitos; painéis de rotas/origens usam parsing LogQL em tempo de consulta; o indicador 429 permanece em painéis de detalhe e segurança como zero observado, sem ocupar o Overview. As APIs Prometheus e Loki aceitaram 31 e 7 consultas de painéis, respectivamente. Os detalhes da execução integrada e os incidentes corrigidos estão em [marco02-validation.md](marco02-validation.md). A correção posterior das categorias do Overview está em [dashboard-overview-fix.md](dashboard-overview-fix.md).
