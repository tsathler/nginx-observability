# Correções finais — Nginx | Overview

**Data:** 2026-11-12
**Grafana:** 12.3.1.
**Dados:** somente tráfego sintético local de app-a, app-b e app-c.

## Rótulos de aplicação

Os instant vectors Prometheus contêm `Time` e `Value`; o label `app` chega como metadado do campo `Value`. A primeira correção usou `Labels to fields`, mas a inspeção visual relatou que somente `app-b` aparecia no eixo, embora as três labels estivessem na API. Esse teste anterior provava os dados de entrada, não o resultado final do gráfico.

A configuração final usa a transformação Grafana **Series to rows**, o `legendFormat` `{{app}}` e `options.xField = "Metric"`. A transformação cria uma linha por série com `Metric` e `Value`; assim o eixo categórico usa o nome da aplicação derivado da série e não o timestamp. O teste consulta a API de datasource do Grafana, verifica o nome de série individual para cada app e confirma que o filtro selecionado reduz o resultado à aplicação escolhida. Esta solução segue o formato documentado de [Series to rows](https://grafana.com/docs/grafana/latest/visualizations/panels-visualizations/query-transform-data/transform-data/).

## Totais HTTP

Os totais usam `increase()` sobre counters do exporter, raspados a cada cinco segundos. `increase()` extrapola as amostras disponíveis até os limites do intervalo selecionado; essa estimativa pode ser fracionária mesmo quando o counter incrementa por evento. A semântica Prometheus é mantida, sem arredondar as consultas e sem substituir a fonte pela leitura de logs, que teria custo e defasagem de ingestão diferentes. Veja a documentação de [`increase()`](https://prometheus.io/docs/prometheus/latest/querying/functions/#increase).

A apresentação dos quatro totais (requisições, 4xx, 5xx e erros por app) usa zero casas decimais, com descrição explícita de que o valor é estimado e arredondado para exibição. Os painéis temporais continuam usando `rate()` em req/s. O ranking de erro ocupa cinco unidades de altura, ante sete; painéis temporais e navegação não foram alterados.

```promql
sum by (app) (increase(nginx_http_response_count_total{app=~"$app"}[$__range]))
```

Total estimado de requisições no período selecionado, por aplicação.

```promql
topk(3,
  sum by (app) (increase(nginx_http_response_count_total{app=~"$app",status=~"4..|5.."}[$__range]))
  or on (app) (0 * sum by (app) (nginx_http_response_count_total{app=~"$app"}))
)
```

Total estimado de respostas de erro no período; a expressão mantém as apps com zero erro. Quando o intervalo não tem tráfego, os testes verificam zero para cada aplicação.

## Validação

- `python tests/verify_pipeline.py --verify-scenarios --verify-persistence` passou: 31 PromQL, 7 LogQL, quatro verificações de categoria/filtro, persistência e cenários de tráfego.
- Os frames de datasource do Grafana apresentam `app-a`, `app-b` e `app-c` como nomes de série distintos; o filtro por `app-b` retorna somente essa série.
- Depois de parar o gerador, três verificações por app confirmaram `increase(...[10s]) = 0` para requisições e erros.
- O JSON dos quatro dashboards foi validado; Compose e `git diff --check` passaram. Os outros três dashboards continuam provisionados com 12, 2 e 12 painéis.
- A confirmação visual por pixels continua indisponível nesta sessão: o host do navegador automatizado não iniciou e o endpoint de render do Grafana informa que não há Image Renderer instalado. A API não foi tratada como prova visual.

## Arquivos alterados neste ajuste

- `scripts/build_dashboards.py` — transformação, eixo categórico, precisão de exibição e altura do ranking.
- `config/grafana/dashboards/nginx-overview.json` — JSON provisionado atualizado.
- `tests/verify_pipeline.py` — nomes de série, filtro por app, semântica de aumento e intervalo ocioso.
- `README.md` e este documento — semântica das contagens e evidências.
