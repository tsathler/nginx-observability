# Auditoria e operação de alertas

## Diagnóstico

Auditoria realizada em 2026-11-13 na stack local do Marco 03.2. O repositório não possuía regras, contact points ou políticas de notificação provisionados. Grafana 12.3.1 e Prometheus 3.8.1 estavam em execução; o endpoint Prometheus confirmou as séries abaixo.

| Sinal | Evidência existente | Decisão |
|---|---|---|
| Requisições/status por app | `nginx_http_response_count_total{app,method,status}` | Calcular proporção 5xx e volume com `increase()` em 1 minuto. |
| Latência | `nginx_http_response_time_seconds_hist_bucket{app,le}` | Calcular P95 por aplicação com `histogram_quantile()` em 1 minuto. |
| Parser do exporter | `nginx_parse_errors_total{app}` | Alertar sobre incremento; tratar como saúde da coleta, separado de falhas da aplicação. |
| Scrapes | `up{job}` para Prometheus e exporter | Adicionar health scrapes de Nginx, app, Loki e Alloy; indisponibilidade não depende de tráfego de usuários. |
| Ingestão de logs | `loki_ingester_wal_disk_full_failures_total`, `loki_ingester_chunks_flush_failures_total`, `loki_write_dropped_entries_total` | Alertar sobre falhas observáveis de flush/WAL e entradas descartadas no writer do Alloy. |
| Prometheus | `prometheus_config_last_reload_successful`, `prometheus_tsdb_storage_blocks_bytes`, `prometheus_tsdb_retention_limit_bytes` | Alertar sobre reload rejeitado e aproximação dos blocos TSDB ao limite configurado. |
| Loki / filesystem | Endpoint `/metrics` de Loki está disponível. A configuração usa armazenamento filesystem, mas não mede a capacidade livre do volume Docker. | Monitorar o scrape do serviço. Documentar falta de sinal confiável de capacidade do volume; não inventar tamanho ou percentual. |
| Exporter durante interrupção | Documentado e reproduzido no teste de confiabilidade do Marco 03.2 | Uma interrupção causa lacuna irrecuperável nos counters do Prometheus, mesmo que os eventos permaneçam em Loki. |

Não havia métricas de saúde da aplicação no Prometheus. O `/health` da aplicação era usado apenas pelo Docker. Foram acrescentados endpoints internos de métricas nas aplicações simuladas e em Nginx. Prometheus os coleta através do Nginx, sem publicar portas adicionais. A consulta app-down é suprimida quando o health scrape de Nginx falha; nesse caso o alerta correto é `Nginx unavailable`.

Alloy já expunha métricas próprias em `12345`, mas o endpoint ficava ligado ao loopback do container. O listener agora é interno à rede Docker e Prometheus o coleta através da rede `metrics`. Essa porta não é publicada no host.

## Regras e limiares

As regras ficam em `config/grafana/provisioning/alerting/alerts.yml`; os limiares específicos de cada aplicação ficam como recording rules em `config/prometheus/rules/alert-thresholds.yml`. Alterar valores por app não exige editar o Compose.

| Alerta | Warning | Critical | Janela e duração |
|---|---|---|---|
| 5xx | >5% e pelo menos 10 respostas | >15% e pelo menos 20 respostas | `increase()` 1m; `for` de 30s / 15s |
| P95 | >500 ms | >1 s | histograma em 1m, mínimo 10 respostas; `for` de 2m / 1m |
| App/Nginx/exporter/Alloy/Loki indisponível | — | Falha de scrape confirmada | `for` 20s |
| Erros de parsing | incremento >0 | — | incremento 5m; `for` 30s |
| Ingestão Loki / descarte Alloy | incremento de falhas WAL/flush ou entries descartadas | critical | incremento 5m; `for` 30s |
| Reload Prometheus inválido | — | `prometheus_config_last_reload_successful=0` | `for` 15s |
| Retenção de blocos TSDB | >80% do limite | >90% do limite | `for` 10m / 5m |

As métricas de requisições são counters em memória no exporter e podem ser estimadas pelas funções `increase()` e `rate()`. Volume mínimo e duração reduzem falsos positivos por amostras pequenas ou picos breves. As regras de 5xx/latência usam a série de threshold por app como zero explícito quando ainda não há counter/histograma por ausência de tráfego, portanto não criam uma notificação `DatasourceNoData` por idle. Se a série de threshold ou a consulta desaparecer de forma inesperada, o estado configurado continua sendo `No Data`; falhas de execução usam `Error`. Regras de disponibilidade observam `up` e diferenciam falha de scrape de falta de tráfego.

Os níveis são exemplos iniciais do laboratório, não SLOs de produção. A latência de warning de 500 ms é deliberadamente ultrapassada pelo cenário sintético `/slower`; o tráfego normal, com requests de aproximadamente 15 ms, não deve dispará-la.

## Contact point e rede

O contact point `Local test webhook` envia ao serviço `alert-receiver`, um servidor Python mínimo em uma rede Docker `alerts` marcada como `internal`. Grafana e o receptor são os únicos membros; não há porta publicada, URL externa ou credencial. O receptor armazena apenas status e labels operacionais (nome, app, severity e component) em memória, até 500 transições. Reiniciar o receptor limpa o histórico de teste.

A política de notificação provisionada aponta para este contact point e agrupa por alerta/app/componente. O receptor permite verificar entrega e resolução, separadamente do estado `Alerting` no Grafana. A árvore local de notification policies é provisionada para o laboratório; mudanças manuais feitas nessa árvore podem ser substituídas no próximo provisionamento.

Para notificações futuras, crie um contact point próprio para o ambiente de destino, armazene credenciais em secret manager ou mecanismo de secrets, habilite TLS e autenticação do webhook, defina políticas/agrupamento e teste entrega/resolução com um endpoint controlado. Não copie o receptor local para produção; ele não tem persistência, autenticação, TLS nem retry durável.

## Armazenamento e limites

Prometheus expõe tamanho dos blocos TSDB e limite de retenção configurado. Os alertas cobrem somente esses blocos; WAL, head chunks, crescimento temporário de compactação e espaço livre no Docker Desktop não são medidos por essa expressão. Por isso, o painel é chamado de “TSDB blocks near retention limit”, não de “disk full”. Loki no backend filesystem não fornece nesta stack um sinal confiável da capacidade livre do volume nomeado. Um alerta real de capacidade exige coletor de métricas do host/volume apropriado, que não foi adicionado ao laboratório.

## Segurança

Os endpoints de métricas são acessíveis somente nas redes internas já usadas pela stack, não adicionam publicação no host e não incluem IPs, caminhos ou IDs de sessão como labels. Os quatro dashboards e seus datasources permanecem inalterados. Dados reais e infraestrutura corporativa não fazem parte da validação.

## Validação ponta a ponta

Em 2026-11-13 foram executados `python tests/verify_alerting.py`, `python tests/verify_pipeline.py --verify-scenarios --verify-persistence`, `python tests/verify_pipeline.py --verify-reliability`, `docker compose config --quiet`, compilação sintática dos scripts Python e `git diff --check`; todos passaram.

O teste de alertas consultou as regras provisionadas na API Grafana e executou suas expressões PromQL contra o Prometheus. Confirmou labels `app` independentes para app-a/b/c, labels `severity`/`component`, `noDataState=NoData`, `execErrState=Error`, contact point e as séries de limiar por aplicação. Todos os targets de saúde (Nginx, três aplicações, exporter, Alloy, Loki e Prometheus) apareceram `up`.

Com o gerador padrão parado por 70 segundos, os alvos de saúde permaneceram normais e as regras de tráfego não entraram em Alerting. Parar app-a gerou `Pending` e `Alerting` para app-a, manteve app-b/app-c e Nginx normais e foi resolvido após reiniciar a aplicação. Parar o exporter e Loki disparou os respectivos alertas de scrape; ambos recuperaram para Normal e houve webhook firing/resolved no receptor local. Quarenta respostas 500 em app-a dispararam as regras warning e critical, preservando isolamento por app. O cenário controlado `/slower` elevou P95 acima do limite warning e o alerta voltou a Normal após cessar o tráfego. A entrega foi confirmada lendo o estado guardado pelo receptor, não inferida do estado Grafana.

O teste completo do Marco 01/02/03.2 também passou: as quatro dashboards mantiveram os painéis/consultas esperados, PromQL/LogQL, segurança, retenção, persistência e recuperação; rotação do access log completou duas vezes. O cenário de confiabilidade observou 21 marcadores únicos no Loki, sete por app, e registrou explicitamente que o exporter não reconstrói counters de requests produzidos enquanto estava indisponível.

Não foi simulado um disco cheio nem crescimento até 80%/90% do TSDB, portanto os limiares de armazenamento foram validados por presença das métricas e avaliação normal da regra, não por disparo. Também não foi injetada uma linha malformada no volume ativo de logs: a regra de parse foi provisionada, a métrica `nginx_parse_errors_total{app}` foi observada zerada e sua expressão foi executada, mas o estado firing por parsing precisa de um ensaio dedicado em volume descartável. Não se alteraram volumes para esses ensaios.

Durante a primeira recriação do Prometheus para carregar a configuração nova, seu log reportou chunks mmap fora de sequência e descarte automático dos arquivos mmap afetados; em seguida, o replay do WAL completou, os targets voltaram e os testes de persistência/reliabilidade passaram. Nenhuma limpeza manual de volume ocorreu. A origem desse aviso não foi determinada nesta tarefa; acompanhe `docker compose logs prometheus` e preserve um backup antes de qualquer reparo futuro. Essa observação é um risco residual de integridade histórica do volume, distinto das regras implementadas.
