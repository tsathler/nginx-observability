# Auditoria de segurança da plataforma

**Escopo:** laboratório local Docker Compose, imagens e configurações deste repositório. Nenhum host corporativo ou dado real foi consultado. Avaliação realizada em 2026-11-13.

## Resumo

O achado mais grave era o Grafana sem autenticação, com acesso anônimo de administrador. Isso foi corrigido: login obrigatório com senha aleatória no `.env` local, arquivo ignorado pelo Git. As APIs Prometheus e Loki continuam sem autenticação própria, mas estão publicadas somente no loopback e isoladas das aplicações por redes Compose internas. Isso é uma configuração de laboratório, não um limite de segurança adequado para exposição corporativa.

| Severidade inicial | Achado e evidência | Situação / risco residual |
|---|---|---|
| Alta | `compose.yaml` permitia `GF_AUTH_ANONYMOUS_ENABLED=true`, papel anônimo `Admin` e login desativado. Qualquer cliente com acesso à porta Grafana podia alterar dashboards e configurações. | Corrigido: autenticação básica local obrigatória, cadastro desativado, senha gerada por `scripts/init_lab_env.py`; teste sem credenciais recebe HTTP 401 e login válido acessa as fontes e os quatro dashboards. |
| Alta | Antes da segmentação, todos os containers compartilhavam a rede padrão, permitindo que uma aplicação simulada comprometida tentasse acessar APIs administrativas sem passar por uma porta publicada. | Corrigido: `frontend`, `metrics` e `logs` são redes internas distintas; aplicações e gerador só participam de `frontend`. Uma rede bridge `host-access` dá acesso ao host apenas a Nginx, Prometheus, Loki e Grafana, cujas portas estão vinculadas a `127.0.0.1`. Exporter e Alloy não publicam portas. |
| Média | Prometheus e Loki aceitam requisições sem autenticação. O Prometheus também tinha `--web.enable-lifecycle`, permitindo recarga da configuração por API. | Lifecycle removido; Prometheus e Loki estão em redes isoladas e suas portas publicadas são loopback. O tráfego HTTP continua sem autenticação/TLS dentro do laboratório e entre aplicações host. Não expor essas APIs em redes não confiáveis. |
| Média | Loki está com `auth_enabled: false`; o servidor Loki não oferece autenticação de usuário embutida nesta configuração. | Mantido para o laboratório local. Para implantação compartilhada, colocar proxy autenticador/API gateway com TLS e controle de tenant à frente do Loki; configurar Alloy e Grafana para autenticar-se. |
| Média | Logs incluem IP de origem, usuário HTTP, URI no campo `request`, referer e user-agent. O campo `path` separado usa `$uri` sem query, mas `request` contém a linha HTTP que pode incluir parâmetros. | Somente tráfego sintético neste laboratório. Em dados reais, definir base legal/finalidade, acesso restrito e retenção; remover ou mascarar query strings, referer, user-agent ou IP quando não forem necessários. Não enviar tokens, cookies ou credenciais na URL. |
| Média | Logs e séries têm volumes persistentes; Loki não configura retenção/expiração nesta stack. A remoção dos containers não apaga volumes. | Os dados do laboratório permanecem até remoção explícita dos volumes. Para corporação, definir retenção e descarte verificável, quotas/alertas de disco, backup protegido e política de restauração. `docker compose down -v` é destrutivo e não é necessário para uso normal. |
| Baixa | Nginx e Alloy usam identidade de container privilegiada (UID 0 na imagem/entrada observada); nenhum container solicita `privileged`, mas nem todos os processos usam usuário não-root. | `no-new-privileges` aplicado a todos e `cap_drop: ALL` onde compatível, inclusive Nginx (o binding de porta 80 é permitido pela configuração do kernel do engine atual). Revalidado pipeline completo. Executar como UID não-root e porta alta é melhoria futura; filesystem raiz permanece gravável em alguns serviços. |
| Baixa | Tags de imagem são explícitas, porém tags podem receber atualização ou ficar defasadas; não há verificação automatizada de CVEs/SBOM neste laboratório. | Atualizar imagens com revisão de changelog, compatibilidade e vulnerabilidades; preferir digests imutáveis e política de atualização em implantação corporativa. |

## Controles implementados

- As quatro portas para uso local (Nginx, Prometheus, Loki, Grafana) são publicadas somente em `127.0.0.1`; Alloy e exporter não publicam portas.
- Grafana requer login local; `.env.example` não contém senha. Execute `python scripts/init_lab_env.py` antes do Compose. O script gera o segredo sem mostrá-lo, não substitui `.env` existente e, se Grafana estiver em execução, sincroniza a senha do usuário admin com a configuração local. Em Windows o arquivo herda a ACL da pasta do usuário; mantenha o diretório privado e não copie `.env` para backups compartilhados.
- A senha é passada ao container pela variável de ambiente do Compose e fica acessível a administradores do daemon Docker e processos locais com privilégio suficiente. Isto é adequado apenas para um laboratório de usuário único; em implantação corporativa use secret store/secret mount e não compartilhe o `.env`.
- Todas as aplicações e serviços recebem `no-new-privileges`; capabilities são removidas para os serviços em que a stack foi validada.
- `frontend`, `metrics` e `logs` são redes `internal: true`. A rede `host-access` existe somente para preservar acesso local às portas e não inclui aplicações, gerador, Alloy ou exporter.
- Configurações são montadas read-only; dados são gravados em volumes nomeados. Não há arquivos de certificados, chaves ou credenciais corporativas no repositório.
- Teste automatizado verifica endereços IP publicados, pertença às redes, flags do Grafana, resposta 401 sem login, leitura autenticada, ausência de `.env`/chaves rastreadas e a presença dos quatro dashboards.

## Separação entre laboratório e implantação corporativa

O laboratório usa HTTP no loopback e nas redes privadas do Compose; essa escolha evita exigir certificados para desenvolvimento local. Para uso corporativo, não publicar diretamente as portas administrativas. Colocar Grafana e APIs atrás de proxy/ingress autorizado, TLS com certificado confiável, MFA/SSO para usuários, e autorização por função. Usar TLS ou mTLS nos caminhos entre hosts e credenciais de serviço geridas por secret store; restringir firewall, egress e redes por serviço. Para Loki, a autenticação deve ser fornecida por proxy/gateway ou por desenho de tenancy compatível, pois o serviço não aplica login de usuário nesta configuração.

Tratar logs como dados potencialmente pessoais e sensíveis: reduzir campos na origem, não registrar secrets em path/query/header, mascarar IP quando a análise não exigir endereço completo, definir retenção curta e acesso auditável, e documentar base legal e resposta a incidente antes de ingestão real. Métricas não devem receber IP, URL completa, session ID ou qualquer identificador de alta cardinalidade.

## Verificação

Com Docker Desktop Linux engine ativo:

```shell
python scripts/init_lab_env.py
docker compose config --quiet
docker compose up -d --build
python tests/verify_pipeline.py --verify-scenarios --verify-persistence
git diff --check
```

Resultado nesta revisão: Compose válido; os testes de segurança confirmaram portas em loopback, APIs administrativas do Grafana não autenticadas retornando 401, acesso autenticado, três redes internas e nenhum `.env`/arquivo de chave rastreado. A suíte integrada verificou as consultas dos quatro dashboards, tráfego sintético, persistência de Prometheus/Loki e Live WebSocket. Ver resultados detalhados no commit/execução atual; tokens e conteúdo de `.env` não são impressos.

## Referências oficiais

- [Grafana: autenticação anônima](https://grafana.com/docs/grafana/latest/setup-grafana/configure-access/configure-authentication/anonymous-auth/) e [configuração via ambiente/Docker](https://grafana.com/docs/grafana/latest/setup-grafana/configure-docker/).
- [Loki: autenticação e proxy](https://grafana.com/docs/loki/latest/operations/authentication/).
- [Prometheus: modelo de segurança](https://prometheus.io/docs/operating/security/) e [TLS para endpoints HTTP](https://prometheus.io/docs/guides/tls-encryption/).
- [Docker Compose: redes internas](https://docs.docker.com/compose/how-tos/networking/) e [opções de segurança/capabilities](https://docs.docker.com/reference/compose-file/services/).
