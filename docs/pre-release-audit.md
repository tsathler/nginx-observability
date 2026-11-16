# Auditoria técnica pré-release v0.1.0

**Auditoria inicial:** 2026-11-13
**Reavaliação da remediação:** 2026-11-16

**Escopo:** revisão independente do repositório e do laboratório local Docker Compose, com tráfego sintético. Nenhum sistema corporativo foi acessado. Nenhum volume foi removido, nenhum histórico foi reescrito, nenhuma tag ou publicação foi criada.
**Decisão inicial:** **NO-GO** pelos motivos descritos no relatório.
**Decisão final — 2026-11-16:** **NO-GO para publicação.** A varredura de todas as imagens utilizadas encontrou candidatos CRITICAL/HIGH sem triagem de alcançabilidade, falsos positivos ou VEX. Também permanecem pendentes a titularidade MIT e a revisão visual de Application Detail/Live Logs. A remediação anterior de versões Nginx/Grafana e a sanitização de logs novos continuam registradas, mas não bastam para aprovar a release.

## Resumo executivo

A arquitetura demonstra um pipeline funcional e testado para três aplicações sintéticas. O estado observado tinha os 11 containers em execução; Grafana, aplicações e Nginx indicavam estado saudável no `docker compose ps`. Os testes anteriormente registrados em `docs/final-audit.md`, `docs/reliability-audit.md` e `docs/alerting-audit.md` comprovam consultas de métricas e logs, isolamento por aplicação, rotação, recuperação de reinícios, estados de alertas e entrega ao receptor local. Esses testes não cobrem recuperação de backup, integridade histórica completa, exame de vulnerabilidades das imagens nem revisão visual recente de todos os painéis.

Na auditoria inicial, Nginx e Grafana tinham avisos que motivaram as atualizações anteriores. A varredura de imagem nesta validação final descobriu dependências adicionais CRITICAL/HIGH nas versões efetivamente usadas; resultados e SBOMs estão em [`docs/sbom/`](sbom/). O número reportado é package-finding, pode contar o mesmo CVE em vários pacotes e repete a mesma base em cinco imagens Python. A ferramenta não avaliou execução/alcançabilidade e não confirmou nem descartou falsos positivos.

Na auditoria inicial os access logs incluíam IP, referer, user-agent e linha HTTP bruta com query string. A remediação de 2026-11-16 sanitizou eventos novos; volumes podem conservar eventos históricos anteriores à mudança. O exporter perde incrementos de métricas durante indisponibilidade, embora logs correspondentes possam continuar pesquisáveis no Loki. Não há restore integral testado para Prometheus, Loki, Grafana e estado Alloy. Essas limitações impedem alegar resiliência/adequação a dados operacionais reais.

## Matriz de achados

| ID | Severidade | Área | Achado e evidência resumida | Bloqueia v0.1.0? |
|---|---|---|---|---|
| A1 | **Média (histórico; mitigado)** | Segurança / dependências | O snapshot inicial usava Nginx 1.29.4. A versão atual 1.30.6 mitigou os avisos auditados; o scan Trivy atual ainda reporta 3 HIGH/2 MEDIUM em pacotes da imagem (A13). | A1 mitigado; **A13 ainda bloqueia** até triagem dos findings atuais. |
| A2 | **Média (histórico; mitigado)** | Segurança / dependências | O snapshot inicial usava Grafana 12.3.1. A versão atual 12.4.15 mitigou o advisory inicial; Trivy ainda reporta 2 HIGH, 4 MEDIUM e 4 UNKNOWN (A13). | A2 mitigado; **A13 ainda bloqueia** até triagem dos findings atuais. |
| A3 | **Média (mitigado para eventos novos)** | Privacidade / logs | Antes da correção, `$request`, referer e user-agent podiam persistir dados sensíveis. Nginx agora permite rotas, remove query strings e exclui cabeçalhos/usuário do log; IP continua registrado e é dado pessoal. | Não para publicar somente fontes/configs, desde que volumes Docker não sejam incluídos. Tráfego real segue bloqueado sem decisão de retenção/acesso e tratamento dos dados históricos. |
| A4 | **Média** | Integridade / métricas | O exporter não reconstrói counters durante indisponibilidade; requests ausentes em Prometheus permanecem apenas nos logs/Loki. Counter em memória reinicia com o processo. | **Não** para laboratório/portfólio, desde que a limitação seja proeminente; sim para alegar contagem completa ou usar como fonte de faturamento/SLO. |
| A5 | **Média** | Backup / restauração | Não há backup automatizado nem restore completo testado. Testes existentes reiniciam serviços e comprovam persistência de alguns marcadores, não recuperação de cópia restaurada. | **Sim** se a release alegar recuperação/backup; caso contrário, remover qualquer ambiguidade e declarar ausência de backup. Para release de laboratório, aceitável com aviso claro. |
| A6 | **Média** | Segurança / fronteira local | Grafana exige autenticação, mas Prometheus e Loki não têm autenticação própria; Loki está com `auth_enabled: false`. Portas são loopback, porém APIs sem autenticação ficam acessíveis a processos do host e a membros de redes Docker autorizadas. | **Não** para lab explicitamente local; **sim** para deployment compartilhado, remoto ou produção. |
| A7 | **Média** | Capacidade / desempenho | Não há limite de CPU/memória por serviço, filesystem read-only geral nem monitoramento confiável do espaço livre dos volumes. Loki filesystem não tem cap por bytes; o limite de Prometheus cobre blocos e não todo o volume. | **Não** para demo, mas deve constar como limitação. Bloqueia alegação de capacidade ou uso compartilhado/produção. |
| A8 | **Baixa** | Supply chain / reprodutibilidade | Imagens são fixadas por tags, não por digest; não há CI nem lock Python. A validação final gerou SBOM SPDX e relatório Trivy para as 11 referências/digests locais; tags ainda não garantem bytes estáveis entre reproduções. | **Sim** em conjunto com A13 enquanto CVEs não forem triadas/remediadas. |
| A13 | **Alta** | Segurança / imagens | Trivy 0.76.2 (DB atualizada em 2026-11-16) encontrou CRITICAL/HIGH em exporter, Loki, Alloy e cinco imagens Python; Grafana, Nginx e Prometheus também têm findings. Ex.: exporter com Go stdlib 1.13.15, cinco CRITICAL; Python base Debian 12.10 com 9 CRITICAL/80 HIGH por imagem; Loki e Alloy com dois CRITICAL cada. | **Sim.** Atualizar/reconstruir imagens ou apresentar triagem reproduzível e VEX justificada para cada candidato CRITICAL/HIGH antes da release. |
| A9 | **Baixa** | Alertas | Regras e entrega firing/resolved ao webhook local foram testadas. O receptor é efêmero, não autenticado, sem TLS, persistência ou retry durável; alerta de espaço livre real não existe. | Não para laboratório. Deve ser informado como mecanismo exclusivamente demonstrativo. |
| A10 | **Baixa** | Dashboards | Consultas e quatro JSONs são cobertos por testes/API; Overview e Security têm registros de inspeção visual; Application Detail e Live Logs permanecem sem validação visual confirmada. | Não para publicação do código se isso estiver explicitado; não alegar validação visual completa. |
| A11 | **Baixa** | Repositório / licença | Histórico verificado para padrões conhecidos sem achados. `LICENSE` MIT cobre conteúdo próprio; componentes AGPL e demais dependências mantêm suas licenças. Titularidade indicada no MIT baseia-se na identidade de commit e carece de confirmação explícita. | **Sim** até confirmar o titular dos direitos e manter avisos/licenças de terceiros corretos. |
| A12 | **Baixa** | Prometheus TSDB | O volume apresentou avisos mmap/out-of-sequence no Prometheus 3.8.1. Após upgrade para 3.16.0 não houve recorrência nos restarts testados; lacunas históricas eventuais não podem ser confirmadas sem fonte independente. | Não para lab, desde que a integridade histórica não seja alegada. Preservar o volume sem reparo destrutivo. |

Na auditoria de 2026-11-13, nenhum achado foi então classificado como Crítico ou Alto. Essa observação precedeu a varredura final e foi supersedida por A13. As APIs administrativas continuam vinculadas ao loopback, não há conexão corporativa configurada e credenciais locais são ignoradas pelo Git; isso não reduz as ocorrências identificadas em dependências de imagens.

## Evidências e reprodução

### 1. Integridade dos dados

**Comprovado:** `config/exporters/nginxlog-exporter.yml` configura o exporter para ler os arquivos de access log e produzir contadores/histogramas por dimensões de baixa cardinalidade. A série de métricas é derivada da leitura contínua dos arquivos, não de uma fila durável de eventos. `docs/reliability-audit.md` registra um ensaio com 21 marcadores únicos, sete por app, recuperados uma vez no Loki depois de rotação e interrupções de Loki/Alloy.

**Limitação reproduzida em teste anterior:** durante parada do exporter foram geradas requisições para cada aplicação. Após voltar, o exporter fez seek para o fim do arquivo ativo; os eventos permaneceram no Loki, porém os contadores Prometheus não foram incrementados retroativamente. Reiniciar o exporter também reinicia os counters em memória. Assim, Prometheus e Loki não são duas cópias equivalentes do mesmo registro: Loki permite investigação do evento, enquanto as métricas podem ter lacunas e `increase()`/`rate()` são estimativas sobre scrapes/counters disponíveis.

**Rotação e offsets:** `scripts/rotate_logs.py` usa rename e `nginx -s reopen` (sem `copytruncate`). O Alloy mantém seu estado no volume `alloy-data`. Os testes registrados observaram continuidade e ausência de duplicação significativa nos marcadores sob a janela ensaiada. Não provam exatamente-once para falha prolongada, arquivo removido antes de ser lido, volume cheio, corrupção de checkpoints ou reinício simultâneo com tráfego ilimitado.

**Prometheus histórico:** a auditoria anterior registra aviso repetido de chunks mmap fora de sequência no Prometheus 3.8.1. A imagem foi atualizada para 3.16.0; reinícios após a atualização não reproduziram o aviso. Como não existe fonte independente de cada amostra histórica, não é possível comprovar que nenhuma lacuna antiga exista. Não reparar nem apagar o volume com base apenas nos logs.

**Como reproduzir sem ação destrutiva:** executar os marcadores e rotação documentados por `python tests/verify_pipeline.py --verify-reliability` apenas em uma cópia/ambiente de teste descartável, pois o teste escreve logs e a política de retenção de arquivos de rotação pode remover arquivos antigos além do limite. Para a inspeção desta auditoria, não foi executado esse teste mutável; foram usados os resultados registrados em `docs/reliability-audit.md` e `docs/final-audit.md`.

### 2. Segurança, privacidade e exposição

**Portas e autenticação:** `compose.yaml` publica Nginx 8080, Prometheus 9090, Loki 3100 e Grafana 3000 em `127.0.0.1`. Exporter, Alloy e receptor não têm porta publicada no host. As redes `frontend`, `metrics`, `logs` e `alerts` são internas; `host-access` é uma bridge separada para acessos locais/integrações explicitamente necessárias. Grafana desativa acesso anônimo e signups e exige `GRAFANA_ADMIN_PASSWORD`; `scripts/init_lab_env.py` gera a credencial local em `.env`, ignorado pelo Git. Prometheus e Loki permanecem sem autenticação interna. A documentação do Loki esclarece que autenticação deve ser provida por camada anterior/proxy ou outro controle de acesso.

**Privilégios:** `no-new-privileges` é aplicado globalmente e `cap_drop: ALL` em vários containers. As aplicações demo usam UID não-root. O Compose não define `read_only`, limites `mem_limit`/`cpus` nem restrições de escrita para todos os serviços; Nginx e Alloy permanecem exceções a UID não-root. Não há `privileged: true` observado. A falta de limites permite que tráfego, consultas ou crescimento de dados consumam recursos do Docker Engine/host.

**Logs sensíveis (snapshot inicial de 2026-11-13):** à época, `config/nginx/default.conf` gravava `remote_addr`, `remote_user`, `$request`, `$http_referer` e `$http_user_agent`. `$request` podia carregar query strings. A implementação atual foi alterada e testes de canário passaram; novos dados estão minimizados, mas os volumes ainda podem conter eventos antigos. Os dashboards evitam indexar IP/caminho como labels de alta cardinalidade, mas usuário autorizado ainda pode consultar/exportar dados de evento. OWASP recomenda excluir, mascarar, sanitizar, hashear ou proteger tokens, senhas, session IDs e PII sensível em logs. Consulte a reavaliação abaixo antes de tráfego real.

**Git:** `.gitignore` exclui `.env`, variantes (mantendo `.env.example`), logs, arquivos rotacionados e cache Python. `python tests/audit_repository_history.py` foi executado nesta auditoria e terminou com `OK: scanned all reachable Git commits; no matching secrets, corporate markers, or sensitive artifact paths found`. O scanner cobre padrões conhecidos específicos e nomes de artefatos, não todos os formatos de segredo, valores aleatórios ou conteúdo local ignorado; não substitui secret scanning contínuo. O `git status` inicial não tinha arquivos rastreados modificados; havia apenas o arquivo de notas de pesquisa desta auditoria, que foi removido antes do commit.

### 3. Backup e restauração

Volumes nomeados existentes: `nginx-logs`, `prometheus-data`, `loki-data`, `alloy-data`, `grafana-data`. O Compose e as instruções não implementam rotina automatizada de backup nem validação de cópia/restauração coordenada. Testes existentes reiniciam Prometheus/Loki e confirmam persistência de marcadores; isso não é teste de restore.

- **Prometheus:** armazenamento local single-node. A restauração precisa de snapshot/coerência do TSDB; cópia direta durante gravação pode não incluir amostras recentes do head/WAL. O limite atual de 7d/1GB não é um backup. Falha do volume Docker pode remover toda a série.
- **Loki:** backend filesystem persistido no volume `loki-data`, retenção de 168h pelo Compactor. Não existe cap de volume nem cópia restaurável validada. Interrupção/cheio do disco pode comprometer ingestão e consulta.
- **Grafana:** volume `grafana-data` persiste SQLite/configuração local; nenhum backup consistente do banco, dashboards não provisionados, usuários e estado foi restaurado num ambiente limpo.
- **Alloy/Nginx:** checkpoints/offsets e logs locais afetam o replay. Restaurar offsets sem os arquivos correspondentes pode provocar duplicação/perda. A estratégia de recuperação coordenada ainda não foi definida.

**Conclusão:** capacidade de backup/restore integral é desconhecida, não “aprovada”. Para um laboratório descartável, declarar que os volumes locais não são backup pode ser suficiente. Para alegar resiliência ou antes de coletar dados de terceiros, criar procedimento versionado, cópia protegida fora do host e ensaio periódico de restore isolado.

### 4. Alertas

`config/grafana/provisioning/alerting/alerts.yml` define alertas provisionados com `NoDataState: NoData` e `ExecErrState: Error`; as regras separam health scrapes de ausência de tráfego e usam thresholds por app, mínimo de volume e períodos `for`. `docs/alerting-audit.md` relata ensaios de indisponibilidade, 5xx, P95 e recuperação, com eventos firing/resolved verificados por API do receptor local.

O contact point é um receptor Python local na rede Docker interna: sem TLS, autenticação, persistência ou retry durável; após restart, o histórico em memória se perde. Isso comprova entrega no cenário de laboratório observado, não entrega confiável sob falha simultânea de Grafana/receptor. A stack também não alerta sobre espaço livre real dos volumes: Prometheus compara tamanho de blocos TSDB ao limite configurado, que não mede WAL/head, compactação nem filesystem; Loki filesystem não fornece nesta configuração uma métrica confiável de capacidade livre. O alerta de parsing foi provisionado, mas os registros anteriores declaram que não foi injetado evento malformado para observar seu disparo.

### 5. Desempenho e escalabilidade

Na captura pontual por `docker stats --no-stream`, os 11 containers consumiam em conjunto aproximadamente 606 MiB de RAM (valores por container somados), com baixa CPU observada durante tráfego demo. A saída indicou limite individual igual à memória disponível do engine (cerca de 7.6 GiB), coerente com a ausência de quotas por serviço. `docker system df` indicou 1.57 GB em volumes locais agregados do daemon, que incluem volumes não necessariamente pertencentes ao projeto; não atribuir esse valor ao laboratório. Essas medições são snapshots e não benchmark nem previsão de produção.

Prometheus mantém retenção 7d e 1GB em blocos; Loki mantém 168h e armazenamento filesystem. Labels principais de métricas usam aplicação/método/status; IP, caminho e parâmetros não são labels Prometheus. No Loki, `app` é label indexada e atributos de requisição permanecem como metadata/conteúdo. Isso reduz cardinalidade, mas queries de segurança que analisam conteúdo de log podem consumir CPU e memória com janelas largas/alta taxa. Não há teste de carga, projeção com número elevado de apps, limites de recursos, quota de logs ou monitoramento do espaço real livre. A taxa sintética atual não demonstra escalabilidade.

### 6. Qualidade, dependências e cadeia de suprimentos

No snapshot inicial as imagens eram (`nginx:1.29.4-alpine`, exporter `v1.9.2`, Prometheus `v3.16.0`, Loki `3.5.7`, Alloy `v1.12.2`, Grafana `12.3.1`; serviços Python usam `python:3.13.2-slim`). Nginx e Grafana foram atualizados para as tags atuais documentadas no Compose. Tags não fixam digest/bytes. Não há workflow CI nem lock Python. SBOMs/SPDX e scan por digest foram gerados nesta validação final; ver os resultados em A13 e `docs/sbom/`.

Foi consultada documentação/avisos oficiais em 2026-11-13. A página oficial NGINX lista CVE-2026-42926 como vulnerável em 1.29.4–1.30.0 e CVE-2026-1642 como vulnerável até 1.29.4; releases corrigidas listadas incluem versões posteriores. CVE-2026-42926 trata de request injection HTTP/2 no módulo proxy; a configuração encontrada usa `proxy_pass`, mas não habilita HTTP/2 no listener, então a exposição da condição completa não foi provada. CVE-2026-1642 trata de upstream SSL; os upstreams desta configuração são HTTP locais, então também não se comprovou caminho afetado. Apesar desses qualificadores, a imagem permanece numa faixa oficialmente vulnerável e deve ser atualizada/avaliada antes de se tornar default de release.

O advisory CVE-2026-27877 informa que Grafana >=12.3.0 e <12.3.6 é afetado quando se usam dashboards públicos com data sources em direct mode. Grafana 12.3.1 está nessa faixa; o repositório provisiona apenas dashboards locais privados e não configura public dashboards, logo a condição descrita não foi encontrada. A existência de patches posteriores e a política Grafana de suporte por minors justificam selecionar e validar um patch atualmente suportado. Nenhuma varredura do conteúdo real das imagens foi realizada, portanto não afirmo ausência de outras CVEs.

### 7. Dashboards e usabilidade

Existem quatro JSONs provisionados em `config/grafana/dashboards`. Os testes/API anteriores verificaram consultas PromQL/LogQL, labels e filtros, painéis, percentis, acesso ao Explore e handshake do endpoint WebSocket do Grafana Live. Um handshake HTTP 101 prova o endpoint, não uma sessão visual de Live tail. Overview e Security têm registros de validação visual nos documentos anteriores. Application Detail e Live Logs seguem com revisão visual pendente; não há screenshots reais no repositório. A auditoria atual não abriu navegador para revalidar a interface, logo não declara validação visual nesta execução.

Semântica importante: rates são estimativas por janela de scrape; totais derivados de `increase()` também podem ser fracionários/extrapolados e a apresentação deve dizer que são estimativas arredondadas. Ausência de dados não deve se confundir com zero/saúde. O teste de API não comprova legibilidade, overflow de tabela, interpretação de cores, filtros visuais ou uso real do Live tail.

### 8. Publicação e licenças

README apresenta arquitetura, quick start, dashboards, cenários, testes, limitações e declaração de que não há homologação de produção. CHANGELOG e notas/checklist locais da release existem; `.gitignore` e scanner de histórico estão em uso. Não há imagens/screenhots falsas. A autoria das adaptações de dashboards e referências é documentada nas auditorias de dashboard/arquitetura. O license audit registra imagens de Grafana e Loki sob AGPL-3.0-only (com exceções/dependências descritas upstream), NGINX com licença BSD-like, exporter/Prometheus/Alloy predominantemente Apache-2.0 e Python PSF; a licença MIT raiz aplica-se somente ao conteúdo próprio e não substitui licenças de componentes.

Antes de publicar: confirmar formalmente o titular indicado no copyright MIT; conservar `LICENSE` e avisos exigidos por software redistribuído; não incluir imagens de container ou dependências redistribuídas sem verificar seus avisos completos. A auditoria disponível não gerou SBOM abrangente de imagens, portanto não afirmar inventário completo de licenças.

## Riscos já mitigados

- Portas de Nginx, Prometheus, Loki e Grafana são vinculadas a loopback; exporter, Alloy e receptor não publicam portas no host.
- Grafana exige autenticação local, anonymous/signups estão desativados, e segredo inicial é criado em `.env` ignorado pelo Git.
- Redes Compose separam frontend, métricas, logs e alertas; `no-new-privileges` é aplicado e capabilities são removidas em diversos serviços.
- Labels Prometheus evitam IPs, URLs completas, session IDs e caminhos de alta cardinalidade.
- Rotação usa rename + reopen, sem `copytruncate`; retenção temporal está configurada para Prometheus e Loki.
- Regras de alertas tratam `No Data` e `Error` explicitamente e têm testes de disparo/recuperação.
- Prometheus foi atualizado para 3.16.0 após os avisos mmap da versão anterior; testes de reinício registrados não reproduziram o aviso.
- Scan local do histórico Git não encontrou correspondências para os padrões de segredo e artefatos sensíveis cobertos pelo script.

## Recomendações do snapshot inicial (2026-11-13; reavaliadas abaixo)

1. Atualizar Nginx para release corrigida/atual suportada — concluído na versão 1.30.6; a varredura final ainda encontrou findings em dependências transitivas, tratados em A13.
2. Atualizar Grafana para patch suportado — concluído na versão 12.4.15; a varredura final ainda encontrou findings em dependências, tratados em A13.
3. Confirmar titularidade/copyright em `LICENSE`; verificar avisos/licenças dos artefatos e registrar o escopo do inventário.
4. Descrever a sanitização nova e o IP retido no README/release; manter a orientação de que só dados sintéticos devem ser usados até concluir tratamento de logs históricos e política de dados reais — texto atualizado no README.
5. Atualizar notas da release para distinguir persistência após restart de backup/restauração. Não alegar backup recuperável; declarar ausência de procedimento restore validado.
6. Executar suíte completa após atualizações — resultados desta reavaliação estão na seção final. Isso não substitui backup/restore nem avaliação de vulnerabilidades.

Essas recomendações são conclusões da auditoria, não autorização para implementar alterações. Nenhuma correção foi iniciada nesta etapa.

## Melhorias recomendadas para v0.2.0

- Projetar fonte durável/reconciliável para métricas HTTP ou documentar formalmente as lacunas, incluindo distinção entre contagem de logs e contagem de séries.
- Criar procedimento e automação de backup/restauração para TSDB, Loki, Grafana e checkpoints Alloy, incluindo ensaio restore em ambiente isolado e RPO/RTO declarados.
- Implementar minimização/redaction configurável de query strings, referer, user-agent e IP, com testes que garantam que segredos sintéticos não chegam ao Loki nem ao access log textual.
- Medir capacidade do filesystem/volumes e definir comportamento em disco cheio; quotas temporais não são quota física.
- Adicionar CI reprodutível, scans de imagens/dependências, SBOM e atualização revisada; avaliar digests imutáveis e proveniência dos artefatos.
- Adicionar limites de CPU/memória, filesystem read-only e execução não-root onde compatíveis; validar os efeitos no Docker Desktop Windows/Linux.
- Exercitar falhas simultâneas Grafana/receptor, parsing malformado, janela sem tráfego, consultas com grande volume e retenção/expiração em volumes temporários descartáveis.
- Concluir revisão visual real de Application Detail e Live Logs e arquivar screenshots genuínas com versão/intervalo de teste, sem dados sensíveis.

## Critérios objetivos de aprovação da release

Considerar **GO** somente quando todos os itens forem evidenciados:

- [ ] Nginx e Grafana atualizados para patches suportados sem avisos aplicáveis às configurações habilitadas, ou uma análise técnica documentada demonstrar não aplicabilidade dos advisories considerados.
- [ ] O direito de aplicar MIT ao conteúdo próprio foi confirmado e avisos de terceiros foram revistos para o escopo publicado.
- [ ] README/release descrevem claramente dados sensíveis nos logs, ausência de redaction e regra de laboratório sintético; não alegam prontidão de produção.
- [ ] Suite de integração, cenários, persistência, confiabilidade, alertas e segurança passa após as atualizações, sem segredos no output ou diff.
- [ ] Quatro dashboards preservam provisioning/consultas; validação visual pendente permanece identificada ou é concluída com evidência real.
- [ ] A release não promete backup/restore, integridade histórica completa ou contagem sem perdas sem um ensaio/prova correspondente.
- [ ] O inventário de imagens/dependências e limitações de supply chain estão explícitos; scan de vulnerabilidades foi executado com ferramenta e data identificadas.

Para publicar como **laboratório educacional**, backup/restauração integral, hardening de produção e visualizações pendentes podem permanecer para v0.2.0 se o README e release comunicarem esses limites. Para qualquer alegação de uso operacional com dados reais, redaction, autenticação das APIs fora do host, controles de capacidade e restore testado são pré-requisitos.

## Verificações desta auditoria

Executado em 2026-11-13, sem parada ou alteração de serviços:

| Comando/inspeção | Resultado |
|---|---|
| `docker compose config --quiet` | Passou. |
| `python tests/audit_repository_history.py` | Passou: nenhum padrão conhecido de segredo, marcador corporativo ou caminho sensível encontrado nos commits alcançáveis. Escopo limitado ao scanner. |
| `git diff --check` | Passou no estado inicial limpo. |
| `git status --short --branch`, `git log -34 --oneline`, `git ls-files` | Branch `main` estava 33 commits à frente de `origin/main`; foram revisados commits locais e arquivos rastreados. Não havia alteração rastreada preexistente. Não há tag local `v0.1.0`. |
| `docker compose ps` | Os 11 serviços estavam em execução; app-a, app-b, app-c, Nginx, Grafana e receptor indicavam healthy. Serviços sem healthcheck próprio estavam Up. Portas exibidas para serviços host estavam em `127.0.0.1`. |
| `docker stats --no-stream` e `docker system df` | Snapshot de memória agregado de ~606 MiB nos 11 containers; sem limites individuais, cada limite mostrado era o limite do engine (~7.6 GiB). O daemon reportou 1.57 GB em volumes locais totais, não atribuídos exclusivamente ao projeto. Não foi realizado benchmark. |
| Avisos/documentação oficial | NGINX Security Advisories, Grafana advisory/support schedule, Prometheus storage, Loki auth/retention, Alloy file source/write, Docker Compose security/secrets/ports, OWASP Logging Cheat Sheet e OpenSSF Scorecard foram consultados em 2026-11-13. Links ao final. |
| Suítes integradas existentes | Não executadas nesta auditoria: os testes de confiabilidade/alertas reiniciam serviços, escrevem logs/métricas e o de rotação pode descartar arquivos antigos fora da janela configurada. Os resultados anteriores permanecem documentados em `docs/final-audit.md`, `docs/reliability-audit.md` e `docs/alerting-audit.md`, não são apresentados como execução independente desta auditoria. |
| Visualização por navegador | Não executada. A inspeção prévia registra limitações visuais pendentes para Application Detail e Live Logs; nenhum screenshot foi criado ou alegado. |

## Referências oficiais consultadas

- NGINX: [Security Advisories](https://nginx.org/en/security_advisories.html) e [notícias/releases de 2026](https://nginx.org/en/2026.html).
- Grafana: [CVE-2026-27877 / versões afetadas](https://github.com/advisories/GHSA-3q27-7qjq-p9c5), [política de suporte e atualização](https://grafana.com/docs/grafana/latest/upgrade-guide/when-to-upgrade/), [back up Grafana](https://grafana.com/docs/grafana/latest/administration/back-up-grafana/).
- Prometheus: [TSDB storage, snapshots e retenção](https://prometheus.io/docs/prometheus/latest/storage/), [security model](https://prometheus.io/docs/operating/security/).
- Loki: [authentication](https://grafana.com/docs/loki/latest/operations/authentication/), [retention](https://grafana.com/docs/loki/latest/operations/storage/retention/), [filesystem storage](https://grafana.com/docs/loki/latest/operations/storage/filesystem/).
- Alloy: [`loki.source.file` e offsets](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.file/), [`loki.write` e retry/WAL](https://grafana.com/docs/alloy/latest/reference/components/loki/loki.write/).
- Docker: [Compose service security options](https://docs.docker.com/reference/compose-file/services/), [port publishing](https://docs.docker.com/engine/network/port-publishing/), [Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/).
- OWASP: [Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html).
- OpenSSF/SLSA: [Scorecard checks](https://scorecard.dev/), [SLSA provenance](https://slsa.dev/spec/v1.2/provenance).

## Conclusão

**Decisão inicial: NO-GO em 2026-11-13.** A causa naquela data incluía versões Nginx/Grafana depois atualizadas e ausência de minimização de logs. O estado atual e os novos bloqueadores são descritos na seção “Validação final da release — 2026-11-16” ao fim deste arquivo.

## Reavaliação após remediação — 2026-11-16

As observações acima descrevem o estado de 2026-11-13. As imagens foram atualizadas e os access logs minimizados para eventos novos; A1–A3 estão tecnicamente remediados no laboratório. A decisão permanece **NO-GO para publicar**: o titular do copyright/MIT ainda não confirmou os direitos, e Application Detail e Live Logs não receberam revisão visual real nesta rodada. Consultas via API não substituem inspeção visual.

### Remediações e evidências atuais

| Achado | Estado atual | Evidência |
|---|---|---|
| A1 — Nginx em faixa sinalizada por advisories | Remediado no laboratório | `compose.yaml` fixa `nginx:1.30.6-alpine`, release estável atual consultada na fonte oficial. `nginx -t`, parsing/exporter e pipeline foram exercitados após atualização. |
| A2 — Grafana em minor sem suporte/patch aplicável | Remediado no laboratório | `compose.yaml` fixa `grafana/grafana:12.4.15`. Migração preservou o volume existente; autenticação, fontes e dashboards passaram. |
| A3 — persistência futura de request/query e headers | Remediado para novas requisições | Nginx grava app, IP de origem, método, rota permitida ou `/_unclassified`, status, duração e bytes. O formato textual para exporter substitui usuário/referer/UA por `-`. `tests/verify_log_privacy.py` enviou marcador sintético em path/query, Cookie, Authorization, Referer e User-Agent; não o encontrou nos logs ativos/rotacionados nem no Loki e confirmou métrica sem labels de IP/path. |
| A4 — lacunas durante indisponibilidade do exporter | Limitação mantida e comprovada | `python tests/verify_pipeline.py --verify-reliability` observou `exporter_outage_events_backfilled=False`; logs permaneceram no Loki, mas não houve reconstrução retroativa dos counters. |
| A5 — restore integral | Limitação mantida | Persistência após restart foi testada, mas nenhum restore de backup coordenado foi executado. Não alegar capacidade de recuperação de backup. |
| A10 — revisão visual incompleta | Pendente | Não houve sessão de navegador nesta remediação. Application Detail e Live Logs continuam sem validação visual confirmada; nenhuma captura foi criada. |
| A11 — titularidade MIT | Pendente e bloqueador de publicação | O arquivo de licença existe, mas não há confirmação do titular. Identidade de commit não prova titularidade. |

Os logs/eventos históricos anteriores à sanitização não foram purgados para preservar os volumes e arquivos existentes. O teste valida ausência do novo canário e o formato dos novos eventos; não prova remoção de todo conteúdo histórico. O laboratório testado usou tráfego sintético. Não houve limpeza de volume.

### Verificações executadas em 2026-11-16

| Verificação | Resultado |
|---|---|
| `python tests/verify_log_privacy.py` | Passou: canário em path/query/Cookie/Authorization/Referer/User-Agent ausente dos logs ativos/rotacionados e do Loki; rota sanitizada, exporter e labels verificados. |
| `python tests/verify_pipeline.py --verify-scenarios --verify-persistence` | Passou: três aplicações, 31 consultas PromQL, 7 LogQL, quatro dashboards, filtros, cenários, controles de autenticação/portas, retenção e persistência após restart. |
| `python tests/verify_pipeline.py --verify-reliability` | Passou: 21 eventos isolados (7/app), dois ciclos de rotação e recuperação do pipeline; limitação do exporter observada. |
| `python tests/verify_alerting.py` | Passou: saúde/ausência de tráfego, indisponibilidade, 5xx, P95, recuperação e entrega ao webhook local. |
| `docker compose config --quiet` | Passou após atualização e sanitização. |
| `python tests/audit_repository_history.py` | Passou na auditoria inicial do histórico alcançável. O scanner cobre padrões conhecidos, não garante ausência de todo segredo. |
| `git diff --check` | Passou após alterações/commits finais. |

Na reavaliação de 2026-11-16, o scan e SBOM completos por digest foram executados; resultados constam na seção final abaixo. O parágrafo anterior descrevia o estado até a primeira remediação. Versões atuais foram comparadas com [NGINX Security Advisories](https://nginx.org/en/security_advisories.html), [NGINX downloads/releases](https://nginx.org/en/download.html), [Grafana v12.4.15](https://github.com/grafana/grafana/releases/tag/v12.4.15) e [Grafana support policy](https://grafana.com/docs/grafana/latest/upgrade-guide/when-to-upgrade/). Nenhuma conexão corporativa, push, tag ou operação destrutiva foi realizada.

### Critérios restantes para GO

- [ ] Obter confirmação explícita do titular dos direitos de aplicar MIT ao conteúdo próprio e revisar atribuições de terceiros.
- [ ] Fazer revisão visual real de Application Detail e Live Logs; manter a pendência explícita se não houver captura/revisão.
- [ ] Revisar/stagear o diff final e repetir verificações no commit candidato.
- [ ] Para alegar ausência ampla de CVEs, produzir inventário/SBOM e scan de imagens com ferramenta, data e limites identificados.

Backup/restore, métricas perdidas durante indisponibilidade do exporter, monitoramento de espaço livre e autenticação/TLS das APIs continuam limitações corporativas. Podem ser apresentadas numa release educacional como limitações explícitas, mas não como homologação para produção.

## Validação final da release — 2026-11-16

### Varredura de imagens e SBOM

O Docker Scout CLI instalado no Docker Desktop exigiu autenticação; não foi feito login nem criada credencial. Como alternativa local foi utilizado Trivy `0.76.2` da [release oficial](https://github.com/aquasecurity/trivy/releases/tag/v0.76.2); o SHA-256 do ZIP Windows foi comparado com o checksum publicado pelo projeto. A base de vulnerabilidades foi atualizada em 2026-11-16. Cada digest local identificado no Compose foi escaneado no Docker Engine. Foram gerados SBOMs SPDX completos e um resumo JSON em [`docs/sbom/`](sbom/). A correspondência entre artefatos e digests está nos SBOMs e `trivy-vulnerability-summary.json`.

| Referência/imagem no Compose | Sistema/base detectada | Findings CRITICAL / HIGH / MEDIUM / LOW / UNKNOWN | Observação |
|---|---|---:|---|
| `nginx:1.30.6-alpine` | Alpine 3.24.4 | 0 / 3 / 2 / 0 / 0 | HIGH reportados em `libxslt`; atualização de Nginx não eliminou risco transitivo. |
| `prom/prometheus:v3.16.0` | Go image | 0 / 2 / 2 / 0 / 4 | Inclui `golang.org/x/net` 0.61.0 com HIGH `CVE-2026-78661`; outros status aparecem UNKNOWN no feed. |
| `grafana/grafana:12.4.15` | Alpine 3.24.3 | 0 / 2 / 4 / 0 / 4 | HIGH associados ao pacote Go `github.com/grafana/tempo`; presença no artefato confirmada, função atingível não determinada. |
| `grafana/loki:3.5.7` | Debian 12.12 + Go | 2 / 54 / 47 / 3 / 6 | HIGH/CRITICAL em bibliotecas Go e pacotes OS. Dois CRITICAL: Go stdlib `CVE-2025-68121`, gRPC `CVE-2026-33186`. |
| `grafana/alloy:v1.12.2` | Ubuntu 24.04 + Go | 2 / 71 / 245 / 85 / 3 | Dois CRITICAL: Go stdlib `CVE-2025-68121`, gRPC `CVE-2026-33186`. |
| `quay.io/martinhelmich/prometheus-nginxlog-exporter:v1.9.2` | Go image | 5 / 69 / 69 / 5 / 2 | Inclui Go stdlib 1.13.15; cinco IDs CRITICAL reportados, incluindo CVE-2023-24538, CVE-2023-24540, CVE-2024-24790 e CVE-2025-68121. |
| `nginx-observability-app-a:latest` | `python:3.13.2-slim`, Debian 12.10 | 9 / 80 / 195 / 143 / 12 | Findings de pacote-base iguais nas cinco imagens Python. |
| `nginx-observability-app-b:latest` | `python:3.13.2-slim`, Debian 12.10 | 9 / 80 / 195 / 143 / 12 | Contagem por finding, não CVEs únicos. |
| `nginx-observability-app-c:latest` | `python:3.13.2-slim`, Debian 12.10 | 9 / 80 / 195 / 143 / 12 | Contagem por finding, não CVEs únicos. |
| `nginx-observability-traffic-generator:latest` | `python:3.13.2-slim`, Debian 12.10 | 9 / 80 / 195 / 143 / 12 | Contagem por finding, não CVEs únicos. |
| `nginx-observability-alert-receiver:latest` | `python:3.13.2-slim`, Debian 12.10 | 9 / 80 / 195 / 143 / 12 | Contagem por finding, não CVEs únicos. |

**Interpretação e aplicabilidade.** O scanner confirmou a presença das versões de pacotes/binaries listadas, não a exploração de um caminho. Os totais são achados pacote-CVE (um CVE pode ser contado em vários pacotes) e as ocorrências Debian se repetem em cada imagem Python. A varredura não faz teste dinâmico, não avalia reachability por código ou exposição de cada endpoint e não decide falsos positivos. Não há VEX aprovada nem CVE classificada como falso positivo confirmado. Portanto: (a) “pacote e versão encontrados” é comprovado; (b) explorabilidade concreta permanece não demonstrada; (c) não aplicabilidade só pode ser afirmada após validar pré-condições e chamadas disponíveis; (d) falso positivo não foi estabelecido.

Exemplo condicional: a descrição de [CVE-2026-33186 no tracker Debian](https://security-tracker.debian.org/tracker/CVE-2026-33186) exige servidores gRPC com interceptor de autorização por caminho e política específica de fallback. Esses elementos não aparecem em `compose.yaml`/configurações provisionadas, mas não foi auditado cada caminho interno dos binários de Loki/Alloy; fica **condicional e sem resolução**, não falso positivo. [CVE-2025-7458 no upstream SQLite](https://www.sqlite.org/cves.html) refere-se a uma chamada C API específica; o scanner atesta a biblioteca instalada, porém a rota de código demo não usa SQLite diretamente. Também não foi emitida exceção de aplicabilidade.

Os resultados bloqueiam a release: exporter `v1.9.2` contém runtime Go antigo com múltiplos CRITICAL; Loki/Alloy e imagens Python têm candidatos CRITICAL/HIGH; existem correções indicadas em feeds para vários achados. Mitigar atualizando/reconstruindo componentes compatíveis, repetir varredura por digest e registrar VEX/justificativa para cada candidato restante. O resumo contém findings, severidades, pacotes, versões instaladas/fixas, links e digests; os SBOMs SPDX contêm o inventário por imagem. Consulte a [release oficial do Trivy 0.76.2](https://github.com/aquasecurity/trivy/releases/tag/v0.76.2) e a [documentação de severidade do scanner](https://trivy.dev/docs/v0.76/guide/scanner/vulnerability/).

### Revisão visual, integridade e publicação

- **Visual:** a CUA não encontrou navegador nem host de automação (`Browsers: []`; erro de conexão do browser host). Não foi possível abrir dashboards nem capturar screenshots. Validação visual permanece pendente para os quatro nesta execução, com prioridade Application Detail e Live Logs. A validação de API anterior não substitui isso. Live tail segue sem evidência de sessão interativa observada.
- **Arquivos sensíveis:** `git ls-files` não contém `.env`, logs `.log`, volumes Docker, screenshots ou dumps operacionais. `.gitignore` exclui `.env` e variantes, logs ativos/rotacionados e bytecode, preservando `.env.example`. O teste de histórico cobre padrões/caminhos conhecidos. Os volumes locais não foram lidos, limpos ou anexados: podem manter eventos anteriores à sanitização, mas não fazem parte do checkout Git verificado.
- **README:** havia texto desatualizado dizendo que eventos novos persistiam request/query, referer e user-agent. Foi corrigido para refletir a minimização atual, indicar risco de volumes históricos e incluir teste de privacidade e evidências SBOM.
- **Licença e backup:** titularidade MIT continua sem confirmação explícita; autoria Git não prova direitos. Licenças dos componentes externos não são alteradas pela raiz MIT. SBOM auxilia inventário, mas não substitui revisão legal de notices. Backup/restore completo continua sem procedimento/teste; persistência após restart não é prova de restauração.
- **Dashboards:** os quatro arquivos continuam no Git e seus JSONs serão validados; não houve redesign nem inspeção visual. Overview/Security têm registros visuais anteriores; Application Detail/Live Logs seguem pendentes.

### Critérios objetivos para reavaliar GO

1. Atualizar/reconstruir componentes CRITICAL/HIGH, incluindo exporter/base Python, e rever Loki/Alloy/Grafana/Nginx/Prometheus. Gerar novos SBOMs e varrer todos os digests usados; para findings restantes, registrar advisory do fornecedor e VEX com precondições, reachability e rationale revisados.
2. Completar inspeção visual real de quatro dashboards, especialmente filtros/tabelas em Application Detail/Live Logs, e observar sessão Live tail com evento sintético. Armazenar screenshots genuínas sem dados sensíveis ou registrar aceite explícito do mantenedor para omiti-las.
3. Confirmar explicitamente titularidade/direito de licenciar MIT e corrigir `LICENSE` se necessário.
4. Validar staging, testes e diffs; garantir que credenciais, logs e volumes não sejam incluídos. Não usar logs históricos do Docker como screenshot/artefato/dado da release.

### Testes executados nesta validação

| Verificação | Resultado em 2026-11-16 |
|---|---|
| `python tests/verify_pipeline.py --verify-scenarios --verify-persistence` | Passou. As três apps retornaram 200/301/403/404/500 e GET/POST; 31 PromQL, 7 LogQL e quatro dashboards verificados; cenários degradação/scan/pico; Grafana Live endpoint 101; auth 401 sem credencial; retenção/persistência após reiniciar Prometheus e Loki. |
| `python tests/verify_pipeline.py --verify-reliability` | Passou. 21 eventos únicos Loki (7/app), duas rotações, recuperação Loki/Alloy/Prometheus/exporter; `exporter_outage_events_backfilled=False`. |
| `python tests/verify_alerting.py` | Passou. Health/idle, outages app/exporter/Loki, 5xx, P95, recuperação e entrega local webhook. |
| `python tests/verify_log_privacy.py` | Passou. Canários de query/path/Cookie/Authorization/Referer/User-Agent ausentes de logs ativos/rotacionados e Loki; rota sanitizada, métrica/exporter verificados. |
| `python tests/audit_repository_history.py` | Passou para padrões e caminhos conhecidos em todos os commits alcançáveis; não substitui secret scanning universal. |
| `docker compose config --quiet` | Passou. |
| JSON dos quatro dashboards, 11 SBOM SPDX e resumo Trivy | Todos parseados com `python -m json.tool`. |
| `git diff --check` | Passou; Git emitiu somente avisos de conversão local LF→CRLF para Markdown, sem whitespace errors. |
| Inspeção visual real | Não executada: inventário CUA retornou `Browsers: []` e erro de host de automação indisponível. Sem screenshots ou alegação de validação visual nesta sessão. |

**Decisão final: NO-GO.** Os critérios 1–3 permanecem incompletos; não criar tag ou release até remediação/justificativa, conclusão visual ou aceite documentado, e confirmação da licença.
