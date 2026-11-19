# Marco 04 — Arquitetura multi-servidor (planejamento)

**Estado:** desenho aprovado pelo mantenedor em 2026-11-17. **Não iniciado.** O Marco 04 só começa depois de concluídas as pendências da release v0.1.0. Nada deste documento está implementado.

## Objetivo

Levar a stack para um servidor Linux central que recebe logs e métricas de vários servidores Nginx, alguns com aplicações publicadas na web, mantendo o dashboard estritamente interno.

## Decisões do mantenedor

| Tema | Decisão |
|---|---|
| Acesso ao Grafana | Somente pela rede interna ou VPN, com HTTPS e login. Nunca publicado na internet: sem porta pública, domínio público ou proxy reverso exposto. |
| Conectividade | Os servidores Nginx monitorados alcançam o central por **rede privada** (IPs internos). |
| Coleta | **Alloy** como agente em cada servidor Nginx, mais um **segundo access log em JSON sanitizado**. O log original de cada servidor permanece intacto. |
| Implantação | O código chega aos servidores por **git** (`git clone` / `git pull`). A configuração específica de cada servidor — IPs, nomes, certificados, credenciais de agentes e do Grafana — é feita **no próprio servidor**, em arquivos fora do controle de versão (como o `.env`), e nunca é commitada. O repositório GitHub é público; o que está nele deve permanecer genérico. |
| Sistema do servidor central | **Ubuntu** 24.04 LTS. |
| Grafana | Usar um **Grafana já existente**, compartilhado com outros dashboards. Esta stack **não sobe Grafana próprio** no central: datasources, dashboards e regras de alerta são instalados nele. |
| Forma de execução | Central com Docker Compose; agentes Alloy nos servidores monitorados — modo (nativo via systemd ou container) **a confirmar**. |
| Inventário | Servidores e aplicações monitorados **a mapear** pelo mantenedor (incluindo requisições/dia por servidor). |


## Servidor central

O central pode ser compartilhado com outros sistemas. Por isso os dados da observabilidade ficam num **volume lógico dedicado** (ex.: 40 GB em `/srv/observability`), para que o Loki nunca encha o disco do sistema, e o Nginx já existente no host serve de **porta de entrada** (TLS + credencial por agente) para Loki e Prometheus, sem expor as portas deles. Os dados do ambiente real (servidores, endereços, levantamentos) ficam fora deste repositório.

Pendências antes da implantação:

1. ✅ Validar os dashboards e regras de alerta no **Grafana 13.x**. Feito em 2026-11-19 com um Grafana `13.2.2` temporário no laboratório, usando o mesmo provisionamento: datasources e 4 dashboards carregados sem erro, 15 regras de alerta com saúde `ok`, ponto de contato criado; `tests/verify_pipeline.py` passou contra ele (`GRAFANA_URL` apontando para o temporário) e a revisão visual no Chrome não mostrou diferença em relação ao 12.4.15. Observação: o provisionamento registra erro inofensivo se a pasta `provisioning/plugins` não existir.
2. Verificar se os UIDs de datasource `prometheus` e `loki` já estão em uso no Grafana existente; se estiverem, adotar UIDs próprios (ex.: `nginx-obs-prometheus`) e ajustar os dashboards.
3. Descobrir como o Grafana existente é implantado (Compose e pasta de provisionamento, ou só UI/API) para escolher entre provisionamento por arquivo e importação via API.
4. Definir o tamanho do volume dedicado e quem o cria (requer root).

## Topologia

```
 Servidores Nginx monitorados (rede privada)           Servidor central Linux
 ┌───────────────────────────────┐                    ┌──────────────────────────────────┐
 │ Nginx                         │                    │ Proxy de entrada (TLS + auth)    │
 │  ├─ access log original       │                    │   ├─> Loki        (logs)         │
 │  └─ access log JSON sanitizado│                    │   └─> Prometheus  (métricas)     │
 │ Alloy (lê o JSON, envia) ─────┼── push saindo ───> │ Grafana (só rede interna/VPN)    │
 └───────────────────────────────┘                    │ Alertas                          │
                                                      └──────────────────────────────────┘
```

- **Envio iniciado pelo agente:** os servidores monitorados não abrem portas novas; apenas o central recebe conexões, e somente dos IPs dos agentes.
- **Uma porta de entrada no central:** Loki e Prometheus não são expostos diretamente; o proxy termina TLS e autentica cada agente.
- **Labels:** cada evento recebe `server` além de `app`. IP de origem, rota e status continuam como campos do evento ou structured metadata, nunca como labels.
- **Fora do servidor central:** as aplicações de demonstração e o gerador de tráfego do laboratório.

## Formato de log nos servidores monitorados

Um `log_format` JSON igual ao de `config/nginx/default.conf`, gravado em arquivo adicional:

- campos: tempo, app, método, rota classificada, status, duração (`request_time`), bytes e IP de origem;
- sem query string, cookies, `Authorization`, `Referer` ou `User-Agent`; caminhos desconhecidos viram `/_unclassified`;
- aplicação com `nginx -t` seguido de `nginx -s reload`, sem derrubar o site;
- o arquivo adicional precisa de rotação própria nos servidores monitorados.

## Pré-requisitos de entrada (gate)

Nenhuma porta do Loki ou do Prometheus pode ser aberta para outra máquina antes de:

1. **Loki corrigido:** ✅ atendido em 2026-11-18 pela reconstrução `ghcr.io/tsathler/loki:3.7.10-go1.26.11-walfix` (ver `docs/cve-triage.md`); trocar por imagem oficial quando houver. Texto original: imagem oficial compilada com Go `1.26.11` ou superior (CVE-2026-97054). Se o Marco 04 começar antes de existir release oficial, rebuild próprio revisado, com SBOM, varredura por digest e regressão completa. A aceitação de risco discutida para a v0.1.0 vale apenas para o laboratório local e não se estende a este cenário.
2. **Transporte protegido:** TLS no proxy de entrada e autenticação por agente (de preferência certificado de cliente/mTLS); firewall do central aceitando somente os IPs dos agentes.
3. **Grafana interno:** bind no IP interno ou atrás de proxy interno com HTTPS; login obrigatório, sem acesso anônimo nem cadastro aberto.
4. **Backup fora do host:** destino protegido e restauração testada. Com dados reais, o backup deixa de ser opcional.
5. **Persistência do Loki:** manter `flush_on_shutdown` e o `stop_grace_period`; reavaliar grafana/loki#25118 na versão adotada.

## Dados pessoais

Os logs das aplicações publicadas contêm IPs de usuários reais. A minimização na origem (formato sanitizado), a retenção de 7 dias e o acesso restrito ao Grafana passam a ser requisitos, não demonstração. Revisar a política de retenção com o responsável pelos dados antes de receber tráfego real.

## Preparação já concluída no laboratório (2026-11-18)

- Rótulo `server` em todos os alvos do Prometheus e nos streams do Alloy (`lab` no laboratório); cada servidor monitorado recebe o seu valor.
- Variável **Server** nos quatro dashboards, aplicada a todas as consultas e aos links do Explore.
- Limites de alerta como padrões aplicados a todo par (server, app) com tráfego, com override opcional por par; alertas HTTP agrupados por `server` e `app`.

## Pontos em aberto para o início do Marco 04

- Sistema e versão do servidor central; forma de execução (Docker Compose no Linux ou serviços nativos).
- Métricas: `remote_write` do Alloy para o Prometheus ou métricas derivadas dos logs; o `nginxlog-exporter` atual roda ao lado do Nginx e não serve a coleta remota como está.
- Dimensionamento de disco e retenção para N servidores.
- Inventário dos servidores e aplicações a monitorar.

## Ensaio com segundo servidor simulado (`lab2`) — 2026-11-19

O perfil Compose `lab2` (desligado por padrão; `docker compose --profile lab2 up -d`) sobe um segundo "servidor" com Nginx, três apps, gerador de tráfego, exporter e um **Alloy que envia** logs ao Loki e métricas ao Prometheus (`remote_write`, rótulo `server="lab2"`), ensaiando o modelo de push deste marco. O Prometheus passou a aceitar gravações remotas (`--web.enable-remote-write-receiver`); no Marco 04 isso fica atrás do proxy com TLS e autenticação.

Resultado do ensaio:

- As métricas e os logs do `lab2` chegaram com `server="lab2"`; os limites de alerta para `lab2/app-a|b|c` foram criados automaticamente pelos padrões, sem editar regras.
- Um cenário de degradação no `lab2` disparou "Elevated/Critical HTTP 5xx ratio" **apenas** para `lab2` (15–24% de 5xx), sem afetar o `lab`. Ao desligar o `lab2`, nenhum alerta ficou preso.
- A variável Server mostrou `lab` e `lab2`; com "All", a faixa de saúde exibiu os 12 componentes identificados por servidor ([captura](screenshots/multi-server-overview.jpg)).
- Corrigido durante o ensaio: "P95 by application" e "5xx share by application" agrupavam só por app, misturando servidores; agora agrupam por servidor e app ("app-a (lab2)"). O alerta "Application unavailable" passou a cruzar app e Nginx por `server` e `instance`.
- Lição de configuração: no Alloy, `scrape_timeout` padrão (10 s) não pode exceder `scrape_interval`; com 5 s é preciso declarar `scrape_timeout` menor.

Pendências para o Marco 04 vistas no ensaio — **resolvidas em 2026-11-19**: "Requests by application", "Applications with the most 5xx", as estatísticas P50/P95/P99, as tendências e tabelas do Security passaram a separar servidor e app ("app-a (lab2)"); as tabelas de log ganharam a coluna Server; a faixa de saúde mantém tamanho mínimo por componente em vez de encolher os rótulos.
