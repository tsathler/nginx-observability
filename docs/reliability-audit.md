# Auditoria de retenção e confiabilidade

**Escopo:** Docker Compose local, serviços simulados e volumes do projeto. Nenhum volume foi removido; não houve acesso corporativo. Auditoria e testes executados em 2026-11-13.

## Diagnóstico inicial

| Componente | Estado encontrado | Risco / evidência |
|---|---|---|
| Prometheus | `--storage.tsdb.retention.time=7d`; sem limite de tamanho configurado. Volume nomeado `prometheus-data`. | O tempo limitava dados antigos, mas volume sem teto por tamanho; crescimento de séries ainda podia consumir o disco Docker. |
| Loki | `auth_enabled: false`, filesystem em volume `loki-data`, sem compactor nem retenção. | Sem política de expiração, os chunks/indexes permaneciam indefinidamente. O modo filesystem não apaga dados por pressão de espaço. |
| Access logs Nginx | Seis arquivos ativos (`app-a/b/c.json` e `.log`) no volume compartilhado `nginx-logs`; sem rotação. | Volume medido em 28,82 MB no início da auditoria e aumentando com tráfego contínuo. |
| Alloy | `loki.source.file` lê os três JSON ativos. `alloy-data` é persistente e contém checkpoints de posição. | Reinício retoma offsets persistidos. O comportamento diante de rename e indisponibilidade do Loki precisava de validação integrada. |
| nginxlog-exporter | Lê os três arquivos de texto ativos; métricas são counters em memória do processo. | O exporter observa renames, reabre o arquivo ativo e continuou a coletar no teste. Ao reiniciar, a versão observada inicia a leitura no fim do arquivo (`Seeked ... Whence:2`); linhas gravadas durante a indisponibilidade não são reprocessadas. Os counters reiniciam. |
| Grafana | Volume nomeado `grafana-data`, 50,68 MB na medição inicial. | Persistência necessária aos dados próprios do Grafana; não é removida pelas políticas novas. |

Medição inicial, via Docker Desktop: `nginx-logs` 28,82 MB; `prometheus-data` 18,41 MB; `loki-data` 1,73 MB; `alloy-data` 395 B; `grafana-data` 50,68 MB. `docker stats` mostrou cerca de 385 MB de memória somada para os dez containers durante tráfego sintético de 2 req/s, em host com 7,6 GiB disponíveis ao engine. São amostras deste laboratório, não garantias de capacidade.

## Políticas implementadas

### Prometheus

Padrão configurável por `.env`:

- `PROMETHEUS_RETENTION_TIME=7d`
- `PROMETHEUS_RETENTION_SIZE=1GB`

O Compose passa os dois limites ao Prometheus. O endpoint de flags confirmou valores efetivos equivalentes a `1w` e `1GiB`. A exclusão ocorre quando o limite de tempo **ou** de tamanho for atingido. O limite por tamanho cobre blocos TSDB, mas WAL, head e compactações podem elevar o uso temporário acima desse valor; reserve margem no disco. A documentação do Prometheus recomenda definir o tamanho de retenção abaixo da capacidade alocada, com folga para compactação.

O volume nomeado mantém dados entre reinícios. O teste de persistência consulta um marcador recente antes e depois do restart de Prometheus. A expiração de dados com sete dias não foi observada, pois exigiria uma janela longa; a política efetiva foi verificada pela API.

### Loki

Padrão configurável por `LOKI_RETENTION_PERIOD=168h` (sete dias, mínimo de 24 horas). A configuração usa TSDB com período de índice diário, Compactor habilitado, diretório de trabalho em `/loki/retention` no volume persistente e `delete_request_store: filesystem`. `max_query_lookback` acompanha o período para manter as consultas dentro da janela configurada.

Loki aplica retenção temporal pelo Compactor, com exclusão assíncrona e atraso operacional; não oferece, no backend filesystem desta stack, retenção por bytes nem remoção ao atingir um percentual do disco. Em disco cheio é necessária intervenção operacional. O período de sete dias foi comprovado na configuração efetiva e dados dentro do período sobreviveram ao restart. A expiração real não foi aguardada nem simulada sobre o volume existente. Teste de expiração futura deve usar projeto/volume descartável separado.

### Rotação de access logs

`scripts/rotate_logs.py` verifica seis arquivos ativos, com padrões configuráveis:

- `NGINX_LOG_ROTATE_BYTES=16777216` (16 MiB por arquivo ativo)
- `NGINX_LOG_ROTATE_KEEP=3` arquivos rotacionados por arquivo ativo.

Quando o limite é atingido, o script renomeia os arquivos no mesmo volume (`.1`, `.2`, ...), remove arquivos além da retenção configurada e envia `nginx -s reopen`. Isso usa o mecanismo documentado do Nginx (USR1) e não usa `copytruncate`. O exporter e o Alloy continuam lendo os arquivos ativos após o Nginx reabri-los. Arquivos renomeados são mantidos para diagnóstico, mas não são fontes configuradas para os coletores.

A rotação é acionada pelo host, sem Docker socket montado em container e sem novo serviço. Para verificação contínua, execute `python scripts/rotate_logs.py --watch --interval 60` enquanto a stack estiver rodando; no Windows, agende `python.exe` e esses argumentos no Agendador de Tarefas. Uma execução única pode ser feita com `python scripts/rotate_logs.py`. O limite é verificado por intervalo, portanto não é uma quota rígida: se o volume de tráfego ultrapassar o limite entre verificações, cada arquivo pode crescer além de 16 MiB. Com seis arquivos, três arquivos retidos por cada ativo e checagem pontual, o orçamento nominal é até 6 × 4 × 16 MiB = 384 MiB, mais o tráfego produzido durante o intervalo e a margem de filesystem.

## Recuperação observada

`python tests/verify_pipeline.py --verify-reliability` executa tráfego sintético local, força duas rotações por rename com requests ativos, e interrompe/reinicia Loki, Alloy, Prometheus e exporter. Identificadores aleatórios por evento são consultados no Loki; counters do exporter são comparados antes e depois de rotação e reinícios.

Resultado validado nesta execução:

- 21 eventos sintéticos (7 por aplicação) apareceram exatamente uma vez no Loki, inclusive eventos gravados durante a parada temporária de Loki/Alloy.
- As duas rotações reabriram os seis arquivos. Antes da interrupção do exporter, os counters Prometheus avançaram ao menos os cinco requests por aplicação gerados nesse período. O exporter reabriu arquivos renomeados durante sua execução.
- O target do exporter voltou a `up` após reiniciar Prometheus e exporter; novas requisições voltaram a incrementar os counters após a recuperação.
- **Limitação observada:** um request por aplicação foi produzido enquanto o exporter estava parado. Após reiniciá-lo, a versão `v1.9.2` usada nesta auditoria de 2026-11-13 (a stack atual usa um rebuild do upstream `v1.11.0`) fez seek para o fim dos arquivos ativos e não fez backfill desses requests nas métricas. Esses requests continuaram consultáveis como logs via Alloy/Loki. Durante restart do exporter, os counters em memória também resetam; Prometheus trata o reset como reinício de counter, mas a contagem anterior não é reconstruída.
- O ensaio histórico verificou a persistência Prometheus, mas a asserção Loki usava rota fixa e janela aberta. A revisão do Marco 03.5 concluiu que esse resultado não identificava a mesma linha após restart; a regressão Loki corrigida e isolada está descrita abaixo.
- As verificações de segurança continuaram passando: endpoints publicados só em loopback, API Grafana 401 sem autenticação, redes segmentadas, e os quatro dashboards provisionados e consultados por API.

### Recuperação do pipeline e garantias

- **Loki indisponível:** os requests permaneceram nos arquivos do Nginx e os identificadores foram recuperados após Loki e Alloy voltarem. Neste ensaio controlado não houve perda ou duplicação. Isso não constitui garantia exactly-once para falhas prolongadas ou disco cheio.
- **Alloy reiniciado:** o volume `alloy-data` conserva offsets; os marcadores posteriores à parada foram enviados uma vez no teste. Se o arquivo ativo/backup sair do alcance do leitor antes que ele esvazie o descritor, podem ocorrer perda ou replay.
- **Prometheus reiniciado:** o volume `prometheus-data` preservou blocos e WAL; o target voltou a ser raspado. Scrapes que coincidem com a parada não existem retroativamente, embora o exporter normalmente exponha o counter acumulado após voltar.
- **Exporter reiniciado:** a coleta de métricas retoma para eventos novos, mas a lacuna de outage não é recuperada. Os access logs e Loki preservam investigação detalhada.

## Testes e limites

```shell
docker compose config --quiet
python tests/verify_pipeline.py --verify-scenarios --verify-persistence
python tests/verify_pipeline.py --verify-reliability
git diff --check
```

O teste integrado também valida consultas PromQL/LogQL e os quatro dashboards. A API Prometheus confirma retenção por tempo/tamanho; `/config` do Loki confirma período e compactor. O teste não espera sete dias para verificar expiração, não força o filesystem a encher e não valida restauração de backup após corrupção do volume. Os dados de retenção permanecem nos volumes nomeados existentes.

## Referências oficiais

- [Prometheus: armazenamento, retenção e espaço extra de compactação](https://prometheus.io/docs/prometheus/latest/storage/).
- [Loki: configuração de retenção e Compactor](https://grafana.com/docs/loki/latest/operations/storage/retention/) e [limitações do filesystem](https://grafana.com/docs/loki/latest/operations/storage/filesystem/).
- [Grafana Alloy: `loki.source.file`, offsets persistidos e recuperação](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.file/).
- [Nginx: sinal USR1 para reabrir arquivos de log](https://nginx.org/en/docs/control.html).
- [Exporter: leitura contínua de access logs](https://github.com/martin-helmich/prometheus-nginxlog-exporter/).

## Marco 03.5 — Persistência do Loki

### Causa e escopo

O teste anterior usava sempre `/app-a/missing` e aceitava qualquer evento correspondente em uma janela aberta até o presente. Um evento antigo ou posterior podia satisfazer a asserção sem provar a persistência da requisição criada pelo teste. `verify_persistence()` agora delega a persistência do Loki para `tests/verify_loki_persistence_isolated.py`, que usa um path sintético aleatório, captura o timestamp e o JSON exatos, e exige a mesma única linha antes e depois do restart.

O Loki `3.7.10` usado nesta stack ainda tem a sequência de remoção/recriação de streams descrita em [grafana/loki#25118](https://github.com/grafana/loki/issues/25118): o estado do stream removido não conserva o contador WAL para a recuperação. O [commit upstream 9cf0657](https://github.com/grafana/loki/commit/9cf0657) adiciona essa preservação. Este marco não troca a imagem nem afirma que o commit esteja incluído na `3.7.10`.

### Mitigação e cobertura

- `config/loki/config.yml` agora declara explicitamente WAL habilitado em `/loki/wal`, checkpoint de cinco minutos e `flush_on_shutdown: true`.
- O serviço principal Loki declara `stop_grace_period: 2m`, permitindo ao Compose enviar SIGTERM e aguardar o flush configurado antes de SIGKILL.
- O fixture isolado testa Loki `3.7.10` com o mesmo ajuste de shutdown e configura chunk idle curto para flush, remoção e recriação do mesmo stream antes do checkpoint. Envia dois eventos sintéticos com labels de stream estáveis e `status`, `method` e `path` como structured metadata. A consulta LogQL filtra os metadados e a asserção compara corpo JSON e timestamp exatos.
- O fixture usa somente `nginx-observability_loki-persistence-regression-data`, projeto Compose próprio e porta loopback 13100. O teste para somente esse Loki isolado; mantém o volume ao final. Não usa build e não executa comandos de limpeza de volume.
- Resultado em 2026-11-17: `python tests/verify_loki_persistence_isolated.py` passou em Loki `3.7.10`; ambos os eventos sobreviveram ao flush/remoção/recriação do stream e ao restart gracioso, com timestamps exatos e filtros de structured metadata. O verificador confirmou que IDs e horários de início dos containers do projeto principal não mudaram.

### Limitação residual

`flush_on_shutdown` protege o encerramento gracioso quando o Loki consegue concluir o flush dentro dos dois minutos. Não garante recuperação após SIGKILL, falha do host, perda do disco ou término do grace period antes do flush. O teste não força esses cenários e não simula falha do volume. A regressão demonstra a mitigação no caminho gracioso; não substitui atualizar para uma release oficial que incorpore a correção upstream de WAL, nem valida a cópia histórica do volume principal.

## Marco 03.6 — Aplicação controlada da mitigação do Loki

**Data:** 2026-11-17, stack principal (`nginx-observability`). Nenhum volume foi removido, limpo ou recriado; não houve build nem push. A execução foi dividida em fases com autorização explícita para cada uma.

### Linha de base (Fase A)

- Após o reboot do Windows, o Docker Desktop iniciou normalmente (engine 29.7.2, kernel WSL2 6.18.58.1). Os cinco volumes do projeto estavam presentes e todos os endpoints responderam (Prometheus, Grafana, Nginx `200`; Loki `ready`; todos os targets `up=1`).
- Os 11 containers principais já estavam em execução, iniciados cerca de dois minutos após o boot, embora o Compose não declare política de restart. A ordem de dependências foi respeitada e os containers antigos foram reutilizados, o que é compatível com `docker compose start`, não com `up`. Nenhuma tarefa agendada ou item de inicialização foi encontrado; a origem do start não foi identificada.
- O container Loki em execução havia sido criado em 2026-11-16, antes do commit `0887f29`: `StopTimeout` padrão (10 s) e hash de configuração do Compose diferente do atual. Como `config/loki/config.yml` é montado do host, o `/config` efetivo já mostrava `flush_on_shutdown: true`. Esse estado híbrido (flush ativo, prazo de 10 s) foi o motivo para antecipar a recriação.
- O encerramento anterior do Loki (após 1h59m de execução) foi gracioso por SIGTERM, mas sem flush, porque esse processo havia iniciado antes da mudança de configuração. O replay do WAL no start seguinte terminou com `errors=false`.
- Contagens consultáveis registradas: 24 h — app-a 13.374, app-b 13.522, app-c 13.543; 7 dias — 55.757, 56.315 e 56.170.

### Aplicação (Fases C e D)

- Rollback preparado: branch local `marco-03.6` a partir de `0887f29`; reverter com `git revert 0887f29` seguido de `docker compose up -d --no-deps loki`. O volume `loki-data` não foi arquivado, para não acrescentar uma parada extra.
- Antes da troca, três marcadores únicos (um por aplicação) foram enviados diretamente à API de push do Loki com o label `job="marco036-marker"`, fora do escopo `job="nginx"` usado pelos dashboards. Também foram congeladas as contagens `job="nginx"` de 30 min e 24 h em um instante fixo já ingerido.
- `docker compose up -d --no-deps loki` levou 4,0 s e não tocou os outros dez serviços. O container antigo recebeu SIGTERM, executou flush imediato de seis streams (três de Nginx e três de marcadores) e encerrou em cerca de 0,5 s. O Alloy recebeu um `500` em um push durante o encerramento e reenviou o lote sem erros posteriores.
- Container novo: `StopTimeout=120`, hash igual ao do Compose atual, mesmo volume `nginx-observability_loki-data`, `flush_on_shutdown: true` no `/config` e recuperação do WAL com `errors=false`.
- Os três marcadores foram recuperados com timestamp e linha exatos, e as contagens congeladas de 30 min e 24 h ficaram idênticas.

### Validação do encerramento (Fase E)

- Três novos marcadores e novas contagens congeladas. `docker compose stop loki` levou 2,18 s: SIGTERM, flush imediato de seis streams em cerca de 17 ms, `Loki stopped` em 0,5 s, `exit 0`, sem OOM. O prazo de 120 s não chegou perto de ser consumido com o volume atual de dados em memória.
- O Loki ficou cerca de 10 s parado; `docker compose start loki` voltou a `ready` em cerca de 18 s, com recuperação do WAL em `errors=false`.
- Os seis marcadores (Fases D e E) e as quatro janelas congeladas foram preservados.
- Linhas reais produzidas durante a parada: a comparação por minuto do campo `time` entre os arquivos JSON do Nginx e o Loki bateu exatamente (16:13 UTC: 33/43/44 em ambos; 16:14 UTC: 41/36/43 em ambos), sem perda nem duplicação.
- `python tests/verify_pipeline.py --verify-scenarios --verify-persistence` passou: 31 consultas PromQL e 7 LogQL, quatro dashboards, Live Logs e websocket do Grafana Live, cenários de degradação, scan e pico, e a regressão isolada. O Loki isolado terminou parado, com seu volume preservado.

### Limites e pendências

- A validação cobre o encerramento gracioso com pouco dado em memória e a configuração padrão de chunks. Não cobre SIGKILL, término do prazo de 120 s, falha do host ou perda do disco.
- O defeito de replay do WAL descrito em [grafana/loki#25118](https://github.com/grafana/loki/issues/25118) continua na imagem `3.7.10`. A mitigação reduz a dependência do replay em paradas graciosas, mas não substitui a atualização para uma release oficial com a correção.
- Linhas com bytes NUL (13 em 7 dias, 4/4/5 por aplicação) coincidem com as quedas do Docker Desktop. A análise está em [Docker Desktop recovery](docker-desktop-recovery.md#retomada-de-2026-11-17-tarde); a origem nos arquivos do Nginx ainda é hipótese.
- Os marcadores sintéticos `job="marco036-marker"` permanecem no `loki-data` até a expiração pela retenção de 168 h.
