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

1. **Loki corrigido:** imagem oficial compilada com Go `1.26.11` ou superior (CVE-2026-97054). Se o Marco 04 começar antes de existir release oficial, rebuild próprio revisado, com SBOM, varredura por digest e regressão completa. A aceitação de risco discutida para a v0.1.0 vale apenas para o laboratório local e não se estende a este cenário.
2. **Transporte protegido:** TLS no proxy de entrada e autenticação por agente (de preferência certificado de cliente/mTLS); firewall do central aceitando somente os IPs dos agentes.
3. **Grafana interno:** bind no IP interno ou atrás de proxy interno com HTTPS; login obrigatório, sem acesso anônimo nem cadastro aberto.
4. **Backup fora do host:** destino protegido e restauração testada. Com dados reais, o backup deixa de ser opcional.
5. **Persistência do Loki:** manter `flush_on_shutdown` e o `stop_grace_period`; reavaliar grafana/loki#25118 na versão adotada.

## Dados pessoais

Os logs das aplicações publicadas contêm IPs de usuários reais. A minimização na origem (formato sanitizado), a retenção de 7 dias e o acesso restrito ao Grafana passam a ser requisitos, não demonstração. Revisar a política de retenção com o responsável pelos dados antes de receber tráfego real.

## Pontos em aberto para o início do Marco 04

- Sistema e versão do servidor central; forma de execução (Docker Compose no Linux ou serviços nativos).
- Métricas: `remote_write` do Alloy para o Prometheus ou métricas derivadas dos logs; o `nginxlog-exporter` atual roda ao lado do Nginx e não serve a coleta remota como está.
- Dimensionamento de disco e retenção para N servidores.
- Inventário dos servidores e aplicações a monitorar.
