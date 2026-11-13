# Nginx Observability

Laboratório local e reproduzível para observar várias aplicações HTTP publicadas pelo mesmo Nginx. Este marco não se conecta a ambientes corporativos: o gerador usa apenas a rede interna do Compose.

## Requisitos

- Docker Desktop com Linux containers e Docker Compose v2.
- Portas locais 8080, 9090, 3100 e 3000 livres (ajustáveis pelo `.env`).
- Aproximadamente 2 GB de memória disponível para os containers.

## Iniciar

```shell
python scripts/init_lab_env.py
docker compose up -d --build
docker compose ps
```

O Compose inicia três aplicações simuladas, Nginx, exporter de access logs, Prometheus, Loki, Alloy, Grafana, gerador contínuo e um receptor local de webhook para testar alertas. O tráfego percorre o proxy Nginx e as respostas são distribuídas entre 200, 301, 403, 404 e 500, incluindo diferentes tempos de resposta. O receptor permanece apenas na rede Docker interna `alerts` e não publica porta no host.

O script cria `.env` (ignorado pelo Git) com uma senha aleatória do Grafana, sem exibi-la, e preserva um arquivo existente. O usuário inicial é `admin`; consulte a senha localmente no `.env` e mantenha esse arquivo privado. Se Grafana já estiver rodando, executar novamente o script sincroniza a senha da instância com o arquivo. Portas e taxa do gerador têm padrões em `.env.example`; ajuste apenas o `.env` local.

## Acessos locais

- Grafana: <http://localhost:3000> (login obrigatório; porta vinculada somente a loopback).
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

### Alertas operacionais

As regras ficam provisionadas em **Grafana → Alerting → Alert rules**, na pasta **Nginx Operations**. Há alertas por aplicação para indisponibilidade, proporção sustentada de 5xx e P95, além de saúde de Nginx, exporter, Alloy, Loki e reload do Prometheus. O pipeline também alerta sobre parse errors do exporter, falhas de flush/WAL no Loki e entradas descartadas pelo writer do Alloy. Os limiares editáveis por aplicação estão em `config/prometheus/rules/alert-thresholds.yml`.

Os padrões são 5xx acima de 5%/15% com mínimo de 10/20 respostas por minuto; P95 acima de 500 ms/1 s com volume mínimo; e `for` entre 15 segundos e 10 minutos conforme o sinal. Consulte causas, ações e estados `No Data`/`Error` nas regras provisionadas e em [docs/alerting-audit.md](docs/alerting-audit.md). As consultas de tráfego produzem zero quando não há eventos, enquanto a indisponibilidade é determinada por health scrapes próprios; ausência inesperada da série de threshold ou erro de datasource permanece visível como `No Data`/`Error`.

O contact point **Local test webhook** entrega ao receptor sem porta publicada ou integração externa. O serviço guarda somente as transições recentes em memória. Para validar regras, estados e entrega/resolução com tráfego sintético local, execute `python tests/verify_alerting.py` (cerca de alguns minutos). A validação interrompe e reinicia temporariamente `app-a`, `nginxlog-exporter` e Loki, dispara 5xx/P95 e deixa o gerador padrão parado durante o ensaio. O script reinicia os serviços e o gerador no `finally`.

Para alterar thresholds por app, edite as recording rules correspondentes à série e labels `app` no arquivo `config/prometheus/rules/alert-thresholds.yml`; a avaliação acompanha os grupos Prometheus. Mudanças no provisionamento Grafana são aplicadas ao reiniciar Grafana. Para notificações reais futuras, configurar endpoint autenticado/TLS, secrets fora do repositório, políticas de roteamento e teste de entrega/resolução em ambiente de destino; o receptor do laboratório não é adequado para produção.

As variáveis de método/status são opções fixas; `$app` é descoberta do label do exporter, portanto aplicações instrumentadas futuramente não exigem duplicar painéis. Application, Method e Status filtram as consultas Prometheus e Loki; Path filtra somente consultas Loki, pois caminho não é label Prometheus. O Loki usa os campos method/status/path/request_time que o Alloy guarda como structured metadata, sem adicionar IP ou URL às labels indexadas. “Slowest by app/method/status/path” mostra a duração máxima em ms por combinação no intervalo selecionado; o cenário normal não gera rotas lentas, então use degradação/pico ou uma requisição sintética `/slower` controlada para preencher esse painel. Methods usa `increase()` de counters e exibe uma estimativa arredondada a requisições inteiras. Most requested paths apresenta contagem de eventos Loki no intervalo, Top 10 ordenado por volume. A tabela recente mostra sete campos de leitura rápida; o payload JSON e os demais campos permanecem disponíveis no Loki/Explore.

## Verificar o pipeline

Com os serviços em execução e Python 3.11 ou superior instalado, rode:

```shell
python tests/verify_pipeline.py
python tests/verify_pipeline.py --verify-persistence
python tests/verify_pipeline.py --verify-scenarios --verify-persistence
python tests/verify_alerting.py
```

O verificador valida respostas 200/301/403/404/500 nas três apps, séries e histogramas isolados, percentis P50/P95/P99, eventos JSON/labels do Loki, targets, zero erros de parse, datasources e quatro dashboards provisionados. Também executa na API real os alvos PromQL e LogQL contidos nos dashboards. `--verify-scenarios` interrompe temporariamente o gerador contínuo, executa os cenários finitos e o reinicia no `finally`. `--verify-persistence` envia uma requisição marcada e reinicia Prometheus e Loki, sem apagar volumes, para verificar que as amostras e o evento permanecem consultáveis. `verify_alerting.py` verifica provisionamento e avalia transições/entrega dos alertas com eventos locais. Para acompanhar logs: `docker compose logs -f nginx alloy loki nginxlog-exporter`.

Os cenários também podem ser executados individualmente. A duração é limitada a 300s, taxa a 20 RPS e concorrência a 4; somente targets localhost/loopback ou o serviço Compose `nginx` são aceitos:

```shell
docker compose stop traffic-generator
docker compose run --rm --no-deps traffic-generator python -u generate.py --scenario normal --duration 30 --rps 4 --concurrency 2
docker compose run --rm --no-deps traffic-generator python -u generate.py --scenario degradation --duration 60 --rps 4 --concurrency 2
docker compose run --rm --no-deps traffic-generator python -u generate.py --scenario scan --duration 30 --rps 4 --concurrency 2
docker compose run --rm --no-deps traffic-generator python -u generate.py --scenario peak --duration 30 --rps 8 --concurrency 2
docker compose run --rm --no-deps traffic-generator python -u generate.py --scenario latency --duration 60 --rps 2 --concurrency 2
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
- Prometheus raspa o exporter, health endpoints internos e métricas de Alloy/Loki a cada 5 segundos. As regras do Grafana usam intervalo de 10 segundos, preservam labels por aplicação com expressões Reduce/Threshold e são provisionadas como código.
- Não usamos o `nginx-prometheus-exporter` oficial para métricas HTTP por app: ele expõe estatísticas globais de `stub_status`, sem status ou latência individual. É adequado como complemento para conexões e estado do Nginx.
- Os dashboards públicos 25257 e 17452 foram avaliados; padrões do 25257 foram adaptados para esta instrumentação. Não foi importado código de painel comunitário sem licença clara. O dashboard 17452 depende das métricas `nginx-prometheus-exporter`/stub_status, ausentes neste laboratório.
- Imagens estão fixadas em versões explícitas; armazenamento Prometheus, Loki, Alloy e Grafana usa volumes nomeados.

Auditoria e comparação de referências: [docs/dashboard-audit.md](docs/dashboard-audit.md). Evidências de runtime e consultas do Marco 02: [docs/marco02-validation.md](docs/marco02-validation.md). Correção das categorias do Overview: [docs/dashboard-overview-fix.md](docs/dashboard-overview-fix.md). Decisões e fontes arquiteturais: [docs/architecture-research.md](docs/architecture-research.md).

Diagnóstico e correções do Application Detail: [docs/application-detail-audit.md](docs/application-detail-audit.md).

## Marco 02 — encerramento e validação

A revisão visual do dashboard Security, após o cenário sintético de varredura, confirmou os painéis Scanner-like paths, Origins with repeated errors e Recent security events. Os resultados foram avaliados como sinais para investigação; respostas 404 não são classificadas automaticamente como ataques. A causa da divergência de intervalo e a correção estão registradas em [docs/security-dashboard-refinement.md](docs/security-dashboard-refinement.md).

A validação visual de Application Detail e Live Logs continua pendente. As consultas e a integração desses dashboards foram verificadas por API; essa verificação não substitui a revisão da renderização no Grafana.

Validação integrada reproduzível: `python tests/verify_pipeline.py --verify-scenarios --verify-persistence`; alertas ponta a ponta: `python tests/verify_alerting.py`. O primeiro comando verifica consultas PromQL/LogQL dos quatro dashboards, separação por aplicação, cenários sintéticos e persistência após reiniciar Prometheus e Loki; o segundo testa alert states e entrega local. Evidências específicas: [Application Detail](docs/application-detail-audit.md), [Live Logs](docs/live-logs-refinement.md), [Security](docs/security-dashboard-refinement.md) e [Alerting](docs/alerting-audit.md).

## Segurança e limitações

As portas Nginx, Prometheus, Loki e Grafana são publicadas no loopback. Aplicações e gerador ficam em rede interna separada das redes de métricas/logs; Alloy e exporter não publicam portas. Grafana exige login, mas Prometheus e Loki não têm autenticação própria nesta configuração local. Loki também depende de um proxy autenticador para autenticação de usuário. Não exponha portas a outras interfaces nem use o Compose demo como configuração corporativa.

O laboratório usa HTTP local, dados sintéticos e volumes persistentes; Loki aplica retenção temporal assíncrona de sete dias. Logs guardam IP, referer, user-agent e o campo request (que inclui a query string), embora `path` separado não a inclua. Antes de ingerir dados reais, reduza/mascare campos, proíba secrets em URLs e defina acesso autorizado. A estratégia corporativa recomendada de TLS, autenticação e proteção de logs está em [docs/security-audit.md](docs/security-audit.md).

## Retenção, rotação e recuperação

Os padrões são Prometheus 7 dias/1 GB de blocos TSDB e Loki 168 horas com Compactor. Ajuste `PROMETHEUS_RETENTION_TIME`, `PROMETHEUS_RETENTION_SIZE` e `LOKI_RETENTION_PERIOD` no `.env`; Loki usa retenção temporal, sem teto de bytes no backend filesystem. O limite de tamanho do Prometheus não cobre todo o WAL/head/compactação nem é quota do volume.

O Nginx escreve seis arquivos no volume `nginx-logs`. Execute `python scripts/rotate_logs.py` para verificar uma vez; `python scripts/rotate_logs.py --watch --interval 60` mantém a verificação recorrente enquanto o processo host estiver ativo. O padrão é 16 MiB por arquivo ativo e três backups por arquivo, usando rename e `nginx -s reopen`. Para execução contínua após logon, agende `python.exe` e esses argumentos no Agendador de Tarefas do Windows. A checagem periódica permite crescimento acima do limite entre execuções.

Para conferir retenção efetiva, rotação e recuperação de interrupções, execute `python tests/verify_pipeline.py --verify-reliability`. O teste cria requests identificáveis localmente, valida ingestão única no Loki, continuidade dos counters através de rotação e reinícios e recuperação dos serviços. O exporter reiniciado começa no fim dos access logs existentes; métricas de requests durante sua parada não são reconstruídas, embora os logs permaneçam disponíveis no Loki. Expiração após sete dias e comportamento em disco cheio exigem observação prolongada e não foram simulados nos volumes atuais. Veja o diagnóstico e limites em [docs/reliability-audit.md](docs/reliability-audit.md).
