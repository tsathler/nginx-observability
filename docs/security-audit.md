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
- `frontend`, `metrics` e `logs` são redes `internal: true`. A rede `host-access` existe somente para preservar acesso local às portas; por ser bridge não-internal, os serviços conectados a ela também podem ter egress via Docker. Ela não inclui aplicações simuladas, gerador, Alloy ou exporter. Em uso corporativo, limitar egress e aplicar política de firewall.
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

## Reavaliação de privacidade e dependências — 2026-11-16

As observações sobre logs acima representam a auditoria de 2026-11-13 e foram mitigadas para novas requisições. `compose.yaml` agora fixa `nginx:1.30.6-alpine` e `grafana/grafana:12.4.15`. A atualização preservou os volumes do laboratório e os testes de integração/auth/dashboard passaram. As versões foram comparadas aos avisos oficiais atuais; nenhum scanner de CVEs/SBOM de imagem foi executado, portanto não se afirma que todas as dependências transitivas estejam livres de vulnerabilidades.

O Nginx não registra mais `$request`, `$remote_user`, `$http_referer` nem `$http_user_agent`. O JSON enviado ao Alloy/Loki inclui horário, aplicação, IP de origem, método, rota allowlisted (ou `/_unclassified`), status, duração e bytes de resposta. O access log textual lido pelo exporter mantém o formato parser-compatível, mas emite hífens para usuário, referer e user-agent; a posição de request contém somente método, caminho sanitizado e protocolo. Cookies e Authorization não são persistidos. O IP completo permanece por finalidade de investigação e correlação local; ele continua sendo dado pessoal e requer controle de acesso/retenção antes de qualquer tráfego real. Caminhos conhecidos de scanner são preservados para análise; caminhos não allowlisted são agrupados e query strings não são armazenadas.

`python tests/verify_log_privacy.py` enviou valor canário apenas sintético no path, parâmetros `access_token`/`password`, Cookie, Authorization, Referer e User-Agent. O teste confirmou sua ausência nos arquivos ativos e rotacionados e nos eventos consultados no Loki, a presença do evento sanitizado e o incremento de métrica com labels limitadas a app/método/status. Isso comprova a sanitização de eventos novos exercitada pelo teste, não a erradicação de dados históricos. Arquivos rotacionados e eventos já existentes nos volumes/Loki não foram purgados; campos antigos podem permanecer até rotação/expiração. Não colete tráfego real nesse laboratório sem tratar esse legado e aprovar finalidade, acesso e retenção.

Validação após as mudanças: `docker compose config --quiet`, `python tests/verify_pipeline.py --verify-scenarios --verify-persistence`, `python tests/verify_pipeline.py --verify-reliability`, `python tests/verify_alerting.py` e `python tests/verify_log_privacy.py` passaram em 2026-11-16. O teste de integração confirmou Grafana 401 sem autenticação e portas publicadas apenas no loopback. Limitações restantes: Prometheus/Loki sem autenticação própria (adequado apenas à fronteira local configurada), ausência de restore integral, ausência de medição confiável de espaço livre, lacunas métricas durante outage do exporter, logs históricos não sanitizados retroativamente e falta de scan completo de imagens.

## Scan de imagens — 2026-11-16

A lacuna de SBOM/CVE acima foi parcialmente fechada com Trivy 0.76.2. O scan cobriu as 11 referências/digests locais do Compose: Nginx, Prometheus, Grafana, Loki, Alloy, nginxlog-exporter e cinco imagens Python de demonstração. SBOMs SPDX e resumo completo dos package findings estão em [`docs/sbom/`](sbom/). O atual sumário relata CRITICAL/HIGH em imagens de base Python, exporter, Loki e Alloy; também há findings HIGH em Grafana, Nginx e Prometheus. A condição bloqueia a release enquanto não forem atualizados/remediados ou avaliados individualmente por advisory e VEX.

Trivy confirma identificação de pacote/versão; não comprova que cada código vulnerável esteja no caminho executado, alcançável por uma entrada externa, nem classifica falsos positivos. Nenhum falso positivo foi confirmado, e não existe VEX aprovado no repositório. `CVE-2026-33186` em gRPC é condicional a certos interceptors/políticas por caminho; a condição não aparece no Compose, mas sem análise de binários/caminhos não foi marcado como não aplicável. Ver [relatório pré-release](pre-release-audit.md) para contagens por imagem, classes de aplicabilidade, decisão NO-GO e critérios de desbloqueio.

O Docker Scout não pôde ser usado sem login; nenhuma credencial foi fornecida ou criada. A alternativa Trivy oficial foi baixada para o diretório global de ferramentas do usuário e o SHA-256 do arquivo Windows conferiu com o checksum da release v0.76.2. A base Trivy foi atualizada em 2026-11-16. O ZIP e cache não fazem parte do repositório.
