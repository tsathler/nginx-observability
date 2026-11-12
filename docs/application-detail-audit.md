# Marco 02.2 — Application Detail audit

Data da auditoria: 2026-11-12. Grafana em execução: 12.3.1. Escopo restrito ao laboratório Docker local e às três aplicações sintéticas.

## Diagnóstico e correções

| Painel/sintoma | Causa confirmada | Correção |
|---|---|---|
| **Methods** mostrava `2026` | A consulta instantânea Prometheus retorna um frame com `Time` e `Value`; `method` fica nos labels do campo `Value`. Sem conversão de série em linhas, o bar chart escolhia o campo temporal como categoria. | `legendFormat: {{method}}`, transformação `seriesToRows` e `xField: Metric`. Os frames da API nomeiam as séries `GET` e `POST`. |
| **Most requested paths** tinha nomes repetidos/confusos | A consulta agrupava por `(app,path)` e o nome da série não explicitava o caminho de forma consistente. Além disso, o parser `| json` expandia campos não necessários. | Agrupar por `path`, manter o filtro `app` no seletor Loki e usar `{{path}}` como série/categoria. O caminho real do log contém o prefixo, por exemplo `/app-a/slower`; app não é repetido no label da categoria. A consulta usa structured metadata do Alloy, sem criar labels de stream. |
| P50/P95/P99 não distinguiam claramente apps | A expressão preservava `app`, mas as séries de range eram reduzidas pelo Stat sem nomes suficientes para distinguir os valores. | Consultas instantâneas com `sum by (le,app)`, legenda `{{app}}` e modo `value_and_name`. Frames de Grafana exibiram display names app-a, app-b e app-c. |
| **Slowest observed requests** aparecia vazio | O cenário `normal` só requisita `/`; não cria `/slow` ou `/slower`. A consulta LogQL funcionou quando uma requisição lenta foi gerada. Uma janela maior com parsing de todo o JSON também ultrapassou o limite de 500 séries do Loki. | Janela `$__range`, filtros sobre structured metadata e `unwrap request_time`. A tabela exibe as colunas app/método/status/caminho e o maior tempo observado por essa combinação no intervalo. A descrição deixa explícita essa agregação. O teste emite `GET /app-a/slower` localmente e exige uma amostra >= 0,7 s no Loki. |
| **Recent requests** mostrava JSON bruto | A visualização Logs exibía a linha JSON inteira como mensagem. | Tabela com extração JSON do campo `Line`, colunas ordenadas/renomeadas e a coluna `Raw event` mantida para acesso ao evento original. Limite de 100 linhas por consulta. |
| Escopo dos filtros | `$app` filtrava as consultas, mas Method/Status eram inconsistentes entre painéis; Path não é label Prometheus. | App/Method/Status filtram métricas onde esses labels existem. App/Method/Status/Path filtram as três consultas Loki (paths, lentidão e eventos recentes). Path continua conteúdo/structured metadata Loki, nunca label Prometheus. |

O status `429` não é produzido pelo gerador atual; o painel permanece útil como zero/ausência quando não existem amostras e respeita os filtros de app, método e status.

## Evidências de consulta

Consultas verificadas contra as APIs reais do laboratório:

```promql
sum by (method) (increase(nginx_http_response_count_total{app=~"app-a",method=~"GET",status=~"2.."}[15m]))
histogram_quantile(0.95, sum by (le, app) (rate(nginx_http_response_time_seconds_hist_bucket{app=~".*",method=~".*",status=~".*"}[1m])))
```

```logql
topk(10, sum by (path) (count_over_time({job="nginx",app=~"app-a"} | method=~"GET" | status=~"2.." | path=~".*slower.*" [15m])))
topk(10, max_over_time({job="nginx",app=~"app-a"} | method=~"GET" | status=~"2.." | path=~".*slower.*" | unwrap request_time | __error__="" [15m]))
{job="nginx",app=~"app-a"} | method=~"GET" | status=~"2.." | path=~".*slower.*"
```

Os testes também conferem os display names de app-a/app-b/app-c e GET/POST, filtro combinado, separação por aplicação e existência dos campos no JSON original.

## Validação e limitação visual

`python tests/verify_pipeline.py --verify-scenarios --verify-persistence` passou: as três apps mantiveram respostas 200/301/403/404/500 e métodos GET/POST; Prometheus/Loki persistiram após reinício; os cenários produziram 47 eventos de sondagem e aumento de 91 requisições; os três checks de intervalo sem tráfego retornaram zero. O verificador reconsultou os 12 painéis do Overview e os quatro dashboards, além dos queries PromQL/LogQL.

Também passaram `docker compose config --quiet`, validação JSON dos quatro dashboards, `python -m py_compile tests/verify_pipeline.py scripts/build_dashboards.py` e `git diff --check`.

Não foi possível fazer captura ou inspeção visual nesta sessão: o serviço de automação informou que o host de navegador estava indisponível, e o ambiente não tem Playwright, Selenium, Pyppeteer ou navegador instalado. Portanto, os frames/consultas e o JSON provisionado foram verificados via API; isso **não** é declarado como confirmação visual da renderização final.

As transformações `Extract fields` e `Organize fields` usadas na tabela seguem a documentação do Grafana: [transformações de dados](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/query-transform-data/transform-data/). Para detalhes, os frames do painel podem ser inspecionados no Grafana via Panel inspector.
