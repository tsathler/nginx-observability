# Auditoria final e prontidão para portfólio

**Data:** 2026-11-13

**Escopo:** repositório local, Docker Compose e dados sintéticos do laboratório. Nenhum host corporativo foi conectado. Nenhum volume foi removido ou reparado manualmente e nenhum push foi executado.

## Resultado executivo

Foi reproduzida a recorrência dos avisos `out of sequence m-mapped chunk` nas inicializações do Prometheus 3.8.1: os logs mostravam a mesma série (`ref 690`) e o chunk anterior, e isso se repetiu em mais de um restart. Apesar do replay do WAL terminar e o serviço iniciar, o descarte de chunks mmap podia deixar lacunas no head histórico.

A versão oficial 3.16.0 contém uma correção de TSDB para preservar chunks mapeados quando o replay WAL combina referências de uma série, evitando amostras out-of-order ausentes e chunks in-order duplicados após restart ([release Prometheus 3.16.0](https://github.com/prometheus/prometheus/releases/tag/v3.16.0)). O Compose foi atualizado de `prom/prometheus:v3.8.1` para `prom/prometheus:v3.16.0`. O volume existente foi reutilizado sem limpeza ou reparo. Após a atualização, os testes de persistência e confiabilidade reiniciaram o Prometheus; o WAL replay completou e nenhum novo aviso mmap fora de sequência apareceu nos logs observados.

Isso reduz a evidência de recorrência no código atualizado, mas não reconstrói amostras já descartadas e não prova completude histórica. A API verifica consultas disponíveis e o teste confirma persistência de marcadores, mas não há uma fonte independente de verdade para comparar todas as amostras antigas. Preserve cópia/snapshot consistente do volume antes de qualquer tentativa futura de reparo. A documentação oficial recomenda snapshots para backup e alerta que armazenamento local é single-node e sem replicação ([Prometheus storage](https://prometheus.io/docs/prometheus/latest/storage/)).

## Auditoria

### Repositório e histórico Git

- Estado inicial limpo: `main` estava `ahead 26` de `origin/main`; os 26 commits foram inspecionados com `git log -26 --oneline`.
- Não há `.env` rastreado em nenhum commit alcançável; `.env.example` é o único arquivo de ambiente versionado e contém valores-modelo sem senha preenchida. `.gitignore` ignora `.env` e variantes, exceto `.env.example`, logs originais/rotacionados, `__pycache__/` e bytecode Python.
- A lista de arquivos rastreados não contém dumps de log, chaves privadas ou arquivos de volume. Foram pesquisados padrões conhecidos de access key AWS, token GitHub, marcador PEM privado e o identificador de host visto em metadados de log; nenhum achado foi encontrado no histórico versionado.
- O endereço `origin` é o GitHub do projeto. Nenhuma conexão de servidor corporativo ou publicação foi realizada. O histórico local permanece sem reescrita.
- Não existe `LICENSE` ou `COPYING`. Nenhuma licença foi escolhida nesta auditoria: antes de anunciar ou distribuir o projeto como open source, o mantenedor precisa decidir e adicionar a licença desejada. Não foi identificado código de dashboard comunitário importado integralmente; referências e adaptações estão registradas em `docs/architecture-research.md` e `docs/dashboard-audit.md`.

### Segurança e exposição

- `docker compose ps` confirmou publicações apenas em loopback: Nginx 8080, Prometheus 9090, Loki 3100 e Grafana 3000. Exporter, Alloy e receptor de alertas não publicam portas no host.
- Grafana exige autenticação local. O teste integrado confirmou HTTP 401 sem credencial. A senha aleatória está em `.env`, fora do Git.
- `frontend`, `metrics`, `logs` e `alerts` são redes internas; a rede `host-access` fornece acesso local controlado aos endpoints publicados. A configuração verificada mantém Prometheus fora das redes de aplicação e alerta.
- Aplicações e ferramentas demo usam usuário não-root. `no-new-privileges` está aplicado em todos os containers; capabilities são removidas onde compatível. Nginx/Alloy e serviços de observabilidade ainda têm exceções de identidade/capabilities e devem ser revistos antes de uma implantação endurecida.
- Todas as imagens usam tags explícitas. O pin Prometheus atualizado é `v3.16.0`; tags não são pins imutáveis por digest. Para releases de produção, validar assinatura/digest, SBOM, política de atualização e avisos de segurança.
- Prometheus e Loki continuam sem autenticação própria. O binding em loopback limita o laboratório ao host, mas não substitui proxy autenticador, TLS e controle de rede em implantação compartilhada.
- Os logs incluem IP, referer, user-agent e request bruto com possível query string. O projeto usa somente dados sintéticos; para dados reais, remover/mascarar campos sensíveis, limitar acesso, retenção e exportação.

### Retenção, rotação e recuperação

- Prometheus usa `PROMETHEUS_RETENTION_TIME=7d` e `PROMETHEUS_RETENTION_SIZE=1GB`. O limite de tamanho aplica-se aos blocos TSDB, não constitui quota do volume e não limita sozinho WAL/head e espaço transitório de compactação.
- Loki usa `LOKI_RETENTION_PERIOD=168h` com Compactor e armazenamento filesystem. A expiração é assíncrona; não há quota por bytes ou métrica confiável de espaço livre do volume nesta stack.
- Nginx escreve seis access logs no volume nomeado. `scripts/rotate_logs.py` renomeia e reabre arquivos com `nginx -s reopen`, sem `copytruncate`; limites por arquivo ativo e backups são configuráveis.
- `python tests/verify_pipeline.py --verify-reliability` confirmou dois ciclos de rotação, 21 eventos sintéticos únicos (sete por app) consultáveis no Loki e recuperação de Loki, Alloy, Prometheus e exporter.
- **Limite do exporter:** ele não faz backfill dos access logs. Requests durante sua indisponibilidade podem aparecer no Loki, mas ficam ausentes dos counters Prometheus; seus counters também reiniciam junto com o processo.
- A retenção temporal de sete dias e expiração real não foram aguardadas. Não houve teste de filesystem cheio, restore de backup nem uso de volume descartável para testar corrupção histórica.

### Alertas

`python tests/verify_alerting.py` verificou regras provisionadas, estados Normal/Pending/Alerting/recuperação e entregas firing/resolved ao receptor local. Testes de indisponibilidade de app, exporter e Loki, erro 5xx e latência P95 passaram. O contact point é apenas um receptor efêmero de laboratório, sem autenticação/TLS, persistência ou garantias de retry; não deve receber alertas de produção.

Alertas de capacidade usam tamanho de blocos TSDB versus limite configurado; não são medição de espaço livre do host ou volume. Para Loki, a ausência de uma fonte confiável de capacidade foi mantida explicitamente, sem criar indicador fictício.

### Dashboards e evidência visual

Os quatro dashboards, seus datasources e consultas PromQL/LogQL foram validados por API real do Grafana/Prometheus/Loki. O teste verificou 31 queries Prometheus, 7 LogQL, categorias, filtros, isolamento de aplicações, eventos, percentis e retenção.

O teste verificou o endpoint Live WebSocket do Grafana com resposta HTTP 101, além do link Explore provisionado; isso valida disponibilidade do endpoint e não uma captura da interface Live tail. A revisão visual de Security foi registrada após conferência do operador em `docs/security-dashboard-refinement.md`. A validação visual de Application Detail e Live Logs permanece pendente conforme `docs/application-detail-audit.md` e `docs/live-logs-refinement.md`. Não há screenshots reais versionadas; nenhum resultado de API é apresentado como captura visual.

## README e reprodução

O README foi reorganizado para apresentação de portfólio: resumo, diagrama, requisitos, início rápido, acessos, dashboards, cenários, verificações, segurança/limitações e mapa do repositório. Detalhes de arquitetura, pesquisas e validações permanecem em `docs/`.

Para reproduzir: instalar Docker Desktop com engine Linux e Python 3.11+, executar `python scripts/init_lab_env.py`, depois `docker compose up -d --build`. O inicializador cria credencial local privada em `.env`; serviços administrativos ficam no loopback. Os testes publicados no README exercitam integração, retenção/persistência, confiabilidade, alertas e composição sem depender de dados corporativos.

## Evidências de validação

Executado em 2026-11-13, com Prometheus 3.16.0 e volumes locais existentes:

| Verificação | Resultado observado |
|---|---|
| `python tests/verify_pipeline.py --verify-scenarios --verify-persistence` | Passou; 3 apps, códigos 200/301/403/404/500, 31 PromQL e 7 LogQL; quatro dashboards; cenários normal/degradação/scan/pico; WebSocket 101; segurança e retenção verificadas; persistência após restart Prometheus/Loki. |
| `python tests/verify_pipeline.py --verify-reliability` | Passou; 21 eventos únicos no Loki, 7 por aplicação, 2 rotações, recuperação dos quatro componentes e ausência de backfill do exporter explicitamente confirmada. |
| `python tests/verify_alerting.py` | Passou antes e depois da atualização; regras, indisponibilidade, 5xx, P95, recuperação e entrega ao webhook local confirmados. |
| `python tests/audit_repository_history.py` | Passou; todos os commits alcançáveis foram analisados para caminhos sensíveis, chaves/tokens comuns, URLs com credenciais e marcadores corporativos, sem imprimir valores. |
| JSON dos quatro dashboards | Os quatro arquivos foram analisados por `python -m json.tool`; sem erro de sintaxe. A integração consultou os mesmos dashboards provisionados no Grafana. |
| `docker compose config --quiet`; `git diff --check` | Ambos passaram após as alterações. |
| Logs de inicialização do Prometheus | Em 3.8.1, o aviso recorria após restarts; em 3.16.0, WAL replay terminou e nenhum `out-of-sequence` foi observado durante a janela dos testes/restarts. |
| Git e dados sensíveis | 26 commits locais sem segredos conhecidos ou `.env` rastreado; nenhum push. |

Os testes não demonstram continuidade completa de toda a série histórica nem ausência de amostras descartadas antes da atualização. São evidência do estado consultável atual, recuperação e ausência de nova recorrência observada.

## Pendências antes de divulgação open source

1. Escolher e adicionar uma licença. Sem isso, não anunciar a distribuição como open source.
2. Produzir capturas reais dos quatro dashboards numa sessão com navegador disponível; revisar visualmente Application Detail e Live Logs.
3. Para publicação mais robusta, fixar imagens por digest e definir processo de atualização/scan de vulnerabilidades.
4. Manter cópia consistente dos volumes e observar Prometheus em uso prolongado; comparar dados históricos com uma fonte independente se for necessário comprovar lacunas.
5. Definir mitigação de campos sensíveis e capacidade de armazenamento antes de ingerir logs de ambientes reais.

## Estado final

As regressões de pipeline não foram observadas após a atualização do Prometheus. A causa provável dos chunks mmap foi endereçada por um upstream fix diretamente relacionado e não se repetiu nos testes executados. A integridade histórica completa permanece inconclusiva. O repositório está tecnicamente preparado para revisão de portfólio, mas a publicação como projeto open source ainda depende da decisão de licença e das capturas/revisões visuais pendentes.
