# Nginx Observability

Laboratório local e reproduzível para observar várias aplicações HTTP publicadas pelo mesmo Nginx. Este marco não se conecta a ambientes corporativos: o gerador usa apenas a rede interna do Compose.

## Requisitos

- Docker Desktop com Linux containers e Docker Compose v2.
- Portas locais 8080, 9090, 3100 e 3000 livres (ajustáveis pelo `.env`).
- Aproximadamente 2 GB de memória disponível para os containers.

## Iniciar

```shell
docker compose up -d --build
docker compose ps
```

O Compose inicia três aplicações simuladas, Nginx, exporter de access logs, Prometheus, Loki, Alloy, Grafana e gerador contínuo. O tráfego percorre o proxy Nginx e as respostas são distribuídas entre 200, 301, 403, 404 e 500, incluindo diferentes tempos de resposta.

As portas e a taxa do gerador têm padrões documentados em `.env.example`; crie um `.env` local para alterá-los.

## Acessos locais

- Grafana: <http://localhost:3000> (modo de laboratório sem login; vinculada somente a loopback).
- Prometheus: <http://localhost:9090>.
- Loki: <http://localhost:3100> (API local, vinculada somente a loopback).
- Aplicações pelo proxy: `http://localhost:8080/app-a/`, `/app-b/` e `/app-c/`.
- Exporter permanece interno à rede Compose.

Quatro dashboards são provisionados automaticamente: **Nginx | Overview**, **Nginx | Application Detail**, **Nginx | Live Logs** e **Nginx | Security**. Use a variável Application (`$app`) para filtrar app-a/app-b/app-c ou todas. Os links no topo navegam entre dashboards preservando variáveis e intervalo.

### Dashboards

- **Overview:** taxas atuais em req/s separadas das contagens estimadas no intervalo, P95, tráfego temporal por status, totais e P95 por app e ranking de erros no período. Totais são exibidos sem casas decimais e identificados como estimativas Prometheus; gráficos comparativos usam uma categoria por aplicação.
- **Application Detail:** seletor de aplicação (inclui All), filtros de aplicação/método/status e Path (somente Loki), total e RPS, P50/P95/P99 identificados por app, categorias de método e rota, Top 10 rotas por volume, maiores durações por app/método/status/caminho em ms e tabela recente com Time, App, Method, Status, Path, Duration (ms) e Source IP.
- **Live Logs:** filtro por app/método/status/path/IP e até 500 eventos; atualização do dashboard em 2s. Para streaming WebSocket genuíno, use o link **Open Loki Explore Live tail** e ative **Live** no Explore. Refresh de painel não é Live tail.
- **Security:** seções Overview, Suspicious Activity e Investigation; taxas atuais req/s com precisão de três casas, 429 como estimativa do período e erros do exporter como saúde da coleta. Methods usa `increase()` arredondado. Scanner-like paths e origens recorrentes exigem o intervalo selecionado e os filtros app/IP; origens requerem ao menos dois erros 4xx/5xx. A tabela recente traz sete campos, em ordem decrescente e com limite de 500 eventos; Explore mantém o JSON completo. São sinais sintéticos para triagem: um 404 isolado não é classificado como ataque.

As variáveis de método/status são opções fixas; `$app` é descoberta do label do exporter, portanto aplicações instrumentadas futuramente não exigem duplicar painéis. Application, Method e Status filtram as consultas Prometheus e Loki; Path filtra somente consultas Loki, pois caminho não é label Prometheus. O Loki usa os campos method/status/path/request_time que o Alloy guarda como structured metadata, sem adicionar IP ou URL às labels indexadas. “Slowest by app/method/status/path” mostra a duração máxima em ms por combinação no intervalo selecionado; o cenário normal não gera rotas lentas, então use degradação/pico ou uma requisição sintética `/slower` controlada para preencher esse painel. Methods usa `increase()` de counters e exibe uma estimativa arredondada a requisições inteiras. Most requested paths apresenta contagem de eventos Loki no intervalo, Top 10 ordenado por volume. A tabela recente mostra sete campos de leitura rápida; o payload JSON e os demais campos permanecem disponíveis no Loki/Explore.

## Verificar o pipeline

Com os serviços em execução e Python 3.11 ou superior instalado, rode:

```shell
python tests/verify_pipeline.py
python tests/verify_pipeline.py --verify-persistence
python tests/verify_pipeline.py --verify-scenarios --verify-persistence
```

O verificador valida respostas 200/301/403/404/500 nas três apps, séries e histogramas isolados, percentis P50/P95/P99, eventos JSON/labels do Loki, target do exporter, zero erros de parse, datasources e quatro dashboards provisionados. Também executa na API real os alvos PromQL e LogQL contidos nos dashboards. `--verify-scenarios` interrompe temporariamente o gerador contínuo, executa os cenários finitos e o reinicia no `finally`. `--verify-persistence` envia uma requisição marcada e reinicia Prometheus e Loki, sem apagar volumes, para verificar que as amostras e o evento permanecem consultáveis. Para acompanhar logs: `docker compose logs -f nginx alloy loki nginxlog-exporter`.

Os cenários também podem ser executados individualmente. A duração é limitada a 300s, taxa a 20 RPS e concorrência a 4; somente targets localhost/loopback ou o serviço Compose `nginx` são aceitos:

```shell
docker compose stop traffic-generator
docker compose run --rm --no-deps traffic-generator python -u generate.py --scenario normal --duration 30 --rps 4 --concurrency 2
docker compose run --rm --no-deps traffic-generator python -u generate.py --scenario degradation --duration 60 --rps 4 --concurrency 2
docker compose run --rm --no-deps traffic-generator python -u generate.py --scenario scan --duration 30 --rps 4 --concurrency 2
docker compose run --rm --no-deps traffic-generator python -u generate.py --scenario peak --duration 30 --rps 8 --concurrency 2
docker compose start traffic-generator
```

O modo `normal` também pode rodar indefinidamente no serviço Compose padrão. Cenários finitos têm seed explícita padrão `42`, respostas variadas e não acessam endereços externos.

Consultas Prometheus úteis:

```promql
sum by (app, status) (rate(nginx_http_response_count_total[1m]))
histogram_quantile(0.95, sum by (app, le) (rate(nginx_http_response_time_seconds_hist_bucket[5m])))
sum by (app, method) (increase(nginx_http_response_count_total[15m]))
sum by (app, status) (rate(nginx_http_response_count_total[1m]))
```

Filtro LogQL por app e leitura do JSON estruturado:

```logql
{job="nginx", app="app-a"} | json
topk(10, sum by (app, path) (count_over_time({job="nginx", app="app-a"} | json | __error__="" [5m])))
topk(10, sum by (remote_addr) (count_over_time({job="nginx", app="app-a"} | json | status=~"4..|5.." [5m])))
```

P95 é calculado a partir do histograma configurado no exporter, que usa `$request_time` do Nginx. A resolução depende dos buckets definidos; não é uma medição exata para cada observação.

Os totais do Overview usam `increase()` em counters raspados a cada cinco segundos. Prometheus extrapola as amostras até o intervalo consultado, portanto o valor pode ser fracionário e é uma estimativa; o Grafana exibe o valor arredondado para a unidade de requisição, sem arredondar a consulta. Em janelas sem tráfego, os painéis mostram zero.

### Evidência da execução local

Em 2026-11-12, o Docker Desktop não estava em execução; WSL reportou `docker-desktop` Stopped, o contexto `desktop-linux` não tinha pipe disponível, e `com.docker.service` estava Stopped. Reabrir o Docker Desktop iniciou a distro e restaurou Docker 29.7.2/Linux. Não foi feito reset, limpeza ou remoção de imagens/volumes. `docker compose up -d --build` recuperou os nove serviços. O teste integrado passou com persistência, cenários e as quatro APIs de dashboard.

Saída representativa do teste com reinício de persistência:

```text
app-a: status=200,301,403,404,500; methods=GET,POST; p95=0.024s; Loki entries=200
app-b: status=200,301,403,404,500; methods=GET,POST; p95=0.024s; Loki entries=200
app-c: status=200,301,403,404,500; methods=GET,POST; p95=0.024s; Loki entries=200
OK: Prometheus target up, zero exporter parse errors; Grafana sources=Loki,Prometheus, panels={'nginx-overview': 12, 'nginx-application-detail': 12, 'nginx-live-logs': 2, 'nginx-security': 12}, verified panel queries={'prometheus': 31, 'loki': 7}, app category/filter checks=4
OK: bounded scenarios produced scan_events=107, request increase=91.0
```

As latências variam entre execuções; a consulta LogQL limita a resposta de verificação a 200 eventos por app. O evento de persistência usa um identificador único na query string da requisição. O teste de cenários confirma tráfego de erro 500, caminhos de varredura indexados somente como campos consultados no Loki e aumento do contador cumulativo. `docker compose ps` terminou com todos os nove serviços running; app-a/b/c, Nginx e Grafana healthy.

## Parar e limpar

```shell
docker compose down
```

Para remover também os dados persistidos do laboratório: `docker compose down -v`.

## Arquitetura e decisões

- Nginx roteia `/app-a/`, `/app-b/`, `/app-c/` e grava um arquivo JSON por aplicação em volume compartilhado. IP e caminho são mantidos como campos do log, nunca como labels Loki/Prometheus.
- `prometheus-nginxlog-exporter` lê os access logs e fornece contagem de respostas por método/status e histogramas de tempo de resposta. O label `app` tem apenas três valores fixos.
- Alloy lê os arquivos JSON, extrai timestamp e metadados e envia eventos ao Loki. O label de aplicação vem do caminho/target fixo; IP e URI ficam nos metadados do evento.
- Prometheus raspa o exporter a cada 5 segundos. Grafana recebe datasources e dashboard por provisioning.
- Não usamos o `nginx-prometheus-exporter` oficial para métricas HTTP por app: ele expõe estatísticas globais de `stub_status`, sem status ou latência individual. É adequado como complemento para conexões e estado do Nginx.
- Os dashboards públicos 25257 e 17452 foram avaliados; padrões do 25257 foram adaptados para esta instrumentação. Não foi importado código de painel comunitário sem licença clara. O dashboard 17452 depende das métricas `nginx-prometheus-exporter`/stub_status, ausentes neste laboratório.
- Imagens estão fixadas em versões explícitas; armazenamento Prometheus, Loki, Alloy e Grafana usa volumes nomeados.

Auditoria e comparação de referências: [docs/dashboard-audit.md](docs/dashboard-audit.md). Evidências de runtime e consultas do Marco 02: [docs/marco02-validation.md](docs/marco02-validation.md). Correção das categorias do Overview: [docs/dashboard-overview-fix.md](docs/dashboard-overview-fix.md). Decisões e fontes arquiteturais: [docs/architecture-research.md](docs/architecture-research.md).

Diagnóstico e correções do Application Detail: [docs/application-detail-audit.md](docs/application-detail-audit.md).

## Marco 02 — encerramento e validação

A revisão visual do dashboard Security, após o cenário sintético de varredura, confirmou os painéis Scanner-like paths, Origins with repeated errors e Recent security events. Os resultados foram avaliados como sinais para investigação; respostas 404 não são classificadas automaticamente como ataques. A causa da divergência de intervalo e a correção estão registradas em [docs/security-dashboard-refinement.md](docs/security-dashboard-refinement.md).

A validação visual de Application Detail e Live Logs continua pendente. As consultas e a integração desses dashboards foram verificadas por API; essa verificação não substitui a revisão da renderização no Grafana.

Validação integrada reproduzível: python tests/verify_pipeline.py --verify-scenarios --verify-persistence. O comando verifica consultas PromQL/LogQL dos quatro dashboards, separação por aplicação, cenários sintéticos e persistência após reiniciar Prometheus e Loki. Evidências específicas: [Application Detail](docs/application-detail-audit.md), [Live Logs](docs/live-logs-refinement.md) e [Security](docs/security-dashboard-refinement.md).

## Limitações do laboratório

Grafana está em modo anônimo e deve permanecer acessível apenas em loopback; não use esta configuração como implantação corporativa. O Loki local não fornece autenticação. Rotação/limite de volume dos logs e gestão operacional de segredos pertencem à próxima etapa. IPs de origem podem ser dados pessoais; a retenção atual é local e deve ser reavaliada antes de qualquer uso real.

Próxima etapa recomendada: avaliar autenticação/TLS, limites/rotação e retenção do Loki/Prometheus, política de privacidade para IPs, alertas operacionais e configuração corporativa desacoplada do Compose demo, tudo em ambiente autorizado e sem levar dados sintéticos como configuração de produção.
