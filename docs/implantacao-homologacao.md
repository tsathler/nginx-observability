# Implantação em homologação (Marco 04)

Guia para levar a stack ao servidor central de homologação e ligar os primeiros servidores Nginx monitorados. O repositório público é o portfólio e permanece genérico: **IPs, nomes, certificados e senhas ficam só nos servidores**, em arquivos fora do git (`.env`, certificados, `htpasswd`).

## Visão geral

```
Servidor monitorado                         Servidor central                     Grafana existente
┌───────────────────────────┐   HTTPS      ┌──────────────────────────────┐     ┌──────────────────┐
│ Nginx → log JSON saneado  │  (push)      │ Nginx do host (TLS, senha    │     │ datasources,     │
│ Alloy (container):        │ ───────────> │ por agente, lista de IPs)    │     │ dashboards e     │
│  • logs → Loki            │              │   ├─> Loki        127.0.0.1  │ <───│ alertas desta    │
│  • métricas → Prometheus  │              │   └─> Prometheus  127.0.0.1  │ rede│ stack            │
└───────────────────────────┘              └──────────────────────────────┘ Docker└────────────────┘
```

| Pacote | Onde | Arquivos |
|---|---|---|
| Central | servidor central | `deploy/central/` (Loki, Prometheus, modelo de entrada no Nginx do host) |
| Agente | cada servidor monitorado | `deploy/agent/` + `config/agent/config.alloy` |
| Grafana | Grafana já existente | `scripts/install_grafana.py` + `deploy/grafana/alert-rules.json` |

O agente é o mesmo do perfil `lab2` do laboratório: o Alloy lê o log JSON, envia as linhas ao Loki e gera as métricas HTTP (`nginx_http_response_count_total`, `nginx_http_response_time_seconds_hist`, `nginx_parse_errors_total`) com os mesmos nomes e rótulos usados pelos dashboards e alertas.

## 1. Servidor central

1. **Volume de dados dedicado** (precisa de root). Exemplo com o espaço livre do grupo LVM:
   ```bash
   sudo lvcreate -L 40G -n observability ubuntu-vg
   sudo mkfs.ext4 /dev/ubuntu-vg/observability
   sudo mkdir -p /srv/observability
   echo '/dev/ubuntu-vg/observability /srv/observability ext4 defaults 0 2' | sudo tee -a /etc/fstab
   sudo mount /srv/observability
   sudo mkdir -p /srv/observability/loki /srv/observability/prometheus
   sudo chown 10001:10001 /srv/observability/loki
   sudo chown 65534:65534 /srv/observability/prometheus
   ```
2. **Código:** `git clone https://github.com/tsathler/nginx-observability.git /opt/nginx-observability` (atualizações com `git pull`).
3. **Configuração:** `cd /opt/nginx-observability/deploy/central && cp .env.example .env` e ajuste retenção e portas no `.env`.
4. **Subir:** `docker compose up -d`. Verificar: `curl -s http://127.0.0.1:13100/ready` e `curl -s http://127.0.0.1:19090/-/ready`.
5. **Entrada para os agentes** no Nginx do host, a partir de `deploy/central/nginx-ingress.conf.example`:
   - certificado TLS em `/etc/nginx/observability/tls/` (CA interna ou certificado da organização);
   - um usuário por agente: `sudo htpasswd -B -c /etc/nginx/observability/agents.htpasswd <nome-do-servidor>` (sem `-c` a partir do segundo);
   - `allow` com o IP privado de cada servidor monitorado; `listen` só no IP privado;
   - `sudo nginx -t && sudo systemctl reload nginx`.
6. **Firewall:** liberar a porta da entrada apenas para os IPs dos agentes; Loki e Prometheus continuam só em `127.0.0.1`.

## 2. Grafana existente

1. **Acesso do Grafana ao Loki e ao Prometheus:** o container do Grafana entra na rede `nginx-observability-central`. No `compose` do Grafana:
   ```yaml
   services:
     grafana:
       networks: [default, nginx-observability-central]
   networks:
     nginx-observability-central:
       external: true
   ```
   (Alternativa provisória: `docker network connect nginx-observability-central <container-do-grafana>`, que se perde se o container for recriado.)
2. **Token:** em Administration → Service accounts, criar `nginx-observability-installer` com papel Admin e gerar um token.
3. **Instalar:** no servidor central,
   ```bash
   cd /opt/nginx-observability
   GRAFANA_TOKEN=<token> python3 scripts/install_grafana.py --grafana-url http://127.0.0.1:3000 --alert-interval 30s
   ```
   Cria os datasources `Nginx Observability - Prometheus/Loki` (UIDs `nginx-obs-prometheus` e `nginx-obs-loki`, sem conflito com os existentes), a pasta **Nginx Observability** com os 4 dashboards e o grupo de 16 regras de alerta. Pode ser repetido após cada `git pull`; use `--dry-run` para ver o que faria.
4. **Notificações:** o script não altera pontos de contato nem políticas. Criar no Grafana uma rota para as regras desta pasta (rótulos `severity`, `component`, `server`, `app`) até o canal da equipe.
5. Revogar ou desativar o token depois da instalação se ele não for reutilizado.

## 3. Cada servidor monitorado

1. **Log JSON saneado** (o log original não muda): copiar `deploy/agent/nginx-observability-log.conf.example` para `/etc/nginx/conf.d/observability-log.conf`, cadastrar as rotas conhecidas no `map`, e em cada site:
   ```nginx
   set $obs_app portal;
   access_log /var/log/nginx/observability/portal.json observability_json;
   ```
   `sudo install -d -o www-data -g adm -m 0750 /var/log/nginx/observability`, depois `sudo nginx -t && sudo systemctl reload nginx`.
2. **Rotação:** `deploy/agent/logrotate.example` → `/etc/logrotate.d/nginx-observability`.
3. **Agente:** `git clone` do repositório, `cd deploy/agent && cp .env.example .env`, preencher `AGENT_SERVER_NAME`, `CENTRAL_URL`, `AGENT_PASSWORD` e `CENTRAL_CA_FILE`; `docker compose up -d`.
4. **Conferir:** `docker compose logs alloy` sem erros; no Grafana, a variável **Server** passa a listar o servidor e o bloco "alloy (servidor)" aparece na faixa de saúde.

## 4. Verificação ponta a ponta

- Overview com **Server = <novo servidor>**: tráfego, P95 e 5xx coerentes com o access log original.
- Live Logs mostra as requisições com a coluna Server.
- Parar o agente (`docker compose stop alloy`) dispara **Monitored server agent stopped sending** para esse servidor em ~3 minutos; ao voltar, o alerta se resolve.
- Uma requisição a `/.env` aparece em Security → "Observed scanner-like paths".

## Checklist antes de receber tráfego real

| # | Item | Responsável | Situação |
|---|---|---|---|
| 1 | Loki com Go ≥ 1.26.11 e correção do WAL | projeto | ✅ imagem própria `3.7.10-go1.26.11-walfix` |
| 2 | TLS + senha por agente + lista de IPs na entrada | implantação | modelo pronto; aplicar no servidor |
| 3 | Grafana só na rede interna/VPN, com login | organização | confirmar no Grafana existente |
| 4 | Backup fora do host com restauração testada | organização | **pendente:** definir destino |
| 5 | Retenção de logs (IPs de usuários) aprovada pelo responsável pelos dados | organização | **pendente** (padrão: 7 dias) |
| 6 | Volume dedicado para os dados | implantação | comando acima (requer root) |
| 7 | Rota de notificação para os alertas | organização | criar no Grafana existente |
| 8 | Inventário de servidores e aplicações | mantenedor | **pendente** |

## Limitações conhecidas

- **Rótulo `server` declarado pelo agente:** a senha identifica o agente na entrada, mas o rótulo `server` vem da configuração dele. Um agente comprometido poderia enviar dados com o nome de outro servidor. Mitigação: uma credencial por servidor, lista de IPs e log de acesso da entrada.
- **Reinício do agente zera os contadores:** `rate()` e `increase()` tratam o reinício; o histórico já enviado não se perde.
- **Saúde de Nginx e aplicações:** nos servidores reais não há os endpoints de saúde do laboratório; a disponibilidade é inferida pelo tráfego, 5xx e pelo alerta de agente parado. Um verificador externo (blackbox) fica para depois.
- **Faixa de saúde:** com muitos servidores, filtre pela variável Server.

## Remoção

- Agente: `docker compose down` em `deploy/agent` (mantém o volume com as posições de leitura) e retirar as duas linhas `set`/`access_log` do site.
- Central: `docker compose down` em `deploy/central`; os dados ficam em `DATA_DIR`.
- Grafana: apagar a pasta **Nginx Observability** (dashboards e regras) e os dois datasources `Nginx Observability - *`.
