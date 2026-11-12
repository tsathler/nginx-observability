# Correção — Nginx | Overview

**Data:** 2026-11-12
**Grafana:** 12.3.1.
**Dados consultados:** tráfego sintético local das apps app-a, app-b e app-c.

## Causa

Os bar charts retornavam Prometheus instant vectors. A API `/api/ds/query` do Grafana entregava cada série como campos `Time` e `Value`, mantendo `app` nos metadados do campo `Value.labels`. Sem transformação, o bar chart selecionava o único campo categórico disponível (`Time`) como eixo; por isso as barras apareciam agrupadas pelo ano/data de 2026 em vez do nome da aplicação.

## Correções

- Os dois bar charts agora aplicam a transformação nativa **Labels to fields** em modo `columns`, que materializa os labels Prometheus em campos categóricos.
- `options.xField` seleciona explicitamente `app` nos gráficos **Requests by application** e **Applications with the most errors**.
- Os painéis distinguem contagens do período (PromQL `increase`) de taxas (PromQL `rate`, unidade req/s). As séries temporais de status, P95 por app e erros ao longo do tempo foram preservadas.
- O ranking de erros usa o total do intervalo selecionado, ordenado com `topk`, e inclui zero para aplicações sem erros. A série temporal separada continua mostrando taxa de erros.
- A faixa de indicadores passou a mostrar taxa atual e total do período para requisições, 4xx e 5xx, além do P95; o indicador 429, sempre zerado neste laboratório sem rate-limit, foi removido do Overview. As taxas/contagens sem amostra usam zero explícito.
- O Overview fica com 12 painéis; os dois gráficos comparativos passaram a ter `app` como eixo categórico e labels expandidos em campos.

## Consultas principais

```promql
sum by (app) (increase(nginx_http_response_count_total{app=~"$app"}[$__range]))
```

Total de requisições no período selecionado por aplicação.

```promql
topk(3,
  sum by (app) (increase(nginx_http_response_count_total{app=~"$app",status=~"4..|5.."}[$__range]))
  or on (app) (0 * sum by (app) (nginx_http_response_count_total{app=~"$app"}))
)
```

Aplicações com mais respostas 4xx/5xx no período, mantendo categorias com zero.

```promql
sum by (app) (rate(nginx_http_response_count_total{app=~"$app",status=~"4..|5.."}[$__rate_interval]))
```

Taxa temporal atual de respostas de erro por app, em requisições por segundo.

## Validação

- `python scripts/build_dashboards.py` gerou os quatro JSONs e o Grafana foi reiniciado para reprovisionar.
- `python tests/verify_pipeline.py` passou, incluindo consultas PromQL/LogQL reais, datasources e os quatro dashboards.
- O teste agora verifica nos JSONs do painel `xField=app`, transformação `labelsToFields`/`columns` e agrupamento `by (app)`.
- Os dois PromQL dos bar charts foram consultados pela API datasource do Grafana. Os frames retornaram labels `app-a`, `app-b` e `app-c`; com filtro `app-b`, só esse label foi retornado.
- Resultado do teste: 31 consultas PromQL e 7 LogQL aceitas; 4 verificações de categoria/filtro passaram; Overview com 12 painéis.
- A consulta de exportação de imagem do Grafana respondeu com o aviso **No image renderer available/installed**; nenhuma imagem placeholder foi mantida como captura. O host de navegador automatizado também estava indisponível. Portanto, a configuração e os dados foram validados contra o Grafana em execução, mas a captura visual de pixels do dashboard ficou pendente.

## Arquivos alterados

- `scripts/build_dashboards.py` — configuração do eixo, transformação, layout, títulos e consultas.
- `config/grafana/dashboards/nginx-overview.json` — JSON provisionado gerado.
- `tests/verify_pipeline.py` — regressão para labels, filtros por app e transformação.
- `README.md` e este documento — descrição e evidência atualizadas.
