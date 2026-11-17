# Docker Desktop recovery — 2026-11-17

## Resultado

Recuperação **parcial e instável**. O daemon respondeu e a stack subiu uma vez, mas Docker Desktop voltou para `stopping` em poucos minutos. A stack não está confirmada como estável no encerramento desta verificação. Não foi retomada a compilação do Loki.

## Evidências e causa provável

- No estado inicial, `docker desktop status` reportava `stopped`, embora `docker info` ainda respondesse. O daemon listava 11 containers parados, 35 imagens e os cinco volumes nomeados do projeto.
- O log do Docker Desktop registrou `WSL_E_USER_VHD_ALREADY_ATTACHED` ao tentar anexar `docker_data.vhdx` e, depois, erro `ERROR_FILE_NOT_FOUND` ao desmontar `docker_data.vhdx`.
- A distro gerenciada `docker-desktop` aparecia em WSL2 como `Running`. O serviço Windows `com.docker.service` estava parado. O daemon Linux respondeu com Docker Engine 29.7.2, kernel WSL2 6.18.58.1, 12 CPUs e 7,606 GiB disponíveis para o engine. `docker system df` registrou 12,26 GB em imagens, 1,596 GB em volumes e 3,646 GB de build cache. A consulta de espaço livre do volume Windows retornou acesso negado; capacidade livre do host permanece desconhecida.
- A causa mais provável do estado oscilante é uma corrida/inconsistência de montagem do VHDX de dados entre o backend do Docker Desktop e o WSL. Os logs demonstram a falha de anexação/desmontagem, mas não estabelecem por que o VHDX já estava anexado. Pressão de recursos durante a compilação é uma hipótese, não confirmada pelos dados disponíveis.

## Procedimentos conservadores executados

1. Inspecionados status, contexto e daemon Docker, containers, imagens, redes, volumes, estado WSL e logs do Desktop.
2. Confirmados por nome os volumes `nginx-observability_alloy-data`, `nginx-observability_grafana-data`, `nginx-observability_loki-data`, `nginx-observability_nginx-logs` e `nginx-observability_prometheus-data`.
3. Sem build, executado `docker compose up -d`. Os containers existentes iniciaram e as aplicações e Grafana reportaram saúde.
4. Loki respondeu `200 ready`; Prometheus `/-/ready` respondeu `200`; Grafana `/api/health` respondeu `200` com banco `ok`.
5. Quando o daemon voltou a `stopping`, solicitados `docker desktop stop` e `docker desktop start`. O status permaneceu `stopping`; `start` respondeu que o Desktop já estava em execução. Nenhum processo foi encerrado à força.

Nenhum volume foi removido, limpo, reparado ou recriado. Não foram executados factory reset, `wsl --unregister`, `docker system prune`, `docker compose down -v` ou reinstalação. Imagens, redes e volumes não foram alterados deliberadamente. A listagem dos volumes foi confirmada antes da última oscilação do daemon; como Docker voltou a ficar indisponível, não foi possível repetir o inventário no estado final.

## Validação e pendências

- `docker compose config --quiet`: passou.
- `docker info`: respondeu durante a janela de recuperação; no encerramento, o daemon voltou a ficar indisponível.
- `docker compose ps`: todos os serviços chegaram a `Up`; a stack não permaneceu acessível até o fim da verificação.
- `python tests/verify_pipeline.py --verify-persistence`: **falhou** em `verify_queries`, porque uma linha retornada pelo Loki continha bytes NUL antes de um evento JSON válido. A falha demonstra uma anomalia nos dados consultados; não basta para concluir corrupção do volume. Arquivos de access log atuais inspecionados no container apresentavam linhas JSON normais. A investigação precisa ser repetida com o engine estável, comparando bytes do arquivo/offsets do Alloy e a resposta da consulta Loki. Nenhuma ação de reparo foi executada.
- A prontidão do Loki e consultas responderam durante a janela, mas a API local ficou inacessível após a nova transição para `stopping`. Integridade histórica completa do Loki não está comprovada.
- O teste de persistência não passou; portanto não há evidência para declarar concluída a validação integrada após esta recuperação.

## Próximas ações seguras

1. Antes de novas tentativas, permitir ao Docker Desktop concluir um encerramento/reinício normal ou reiniciar o Windows em janela apropriada, sem tarefas de escrita no engine. Isso interrompe workloads locais, mas não requer remoção de dados; não executar correções de VHDX.
2. Ao voltar, verificar `docker info`, `docker volume ls`, IDs dos containers/imagens e `docker compose ps` antes de subir a stack. Se qualquer volume esperado faltar ou houver erro de montagem/TSDB, parar e preservar o estado para avaliação, sem recriar volume.
3. Subir sem build e testar primeiro health endpoints; então repetir integração/persistência e investigar a linha NUL. Não executar rebuild do Loki nesta etapa.
4. Se o erro `WSL_E_USER_VHD_ALREADY_ATTACHED` persistir, coletar logs do Desktop/WSL e buscar suporte do Docker/Microsoft antes de qualquer reparo do disco de dados.

## Retomada de 2026-11-17 (tarde)

### Backup do disco de dados

Existe uma cópia consistente do disco de dados do Docker Desktop em `C:\Docker-Backup\docker_data-backup-consistente.vhdx` (22.630.367.232 bytes, gravada em 2026-11-17 às 10:11 -03). Ela deve ser preservada. O disco ativo `%LOCALAPPDATA%\Docker\wsl\disk\docker_data.vhdx` voltou a ser gravado depois disso, portanto o backup **não** contém o estado mais recente dos volumes.

### Nova falha de inicialização do engine

- Às 12:53 -03, `docker desktop start --timeout 300` terminou com `context deadline exceeded`. O log do backend registrou `wsl-bootstrap run ... --data-disk ...` com `Wsl/Service/ERROR_OPERATION_ABORTED`, seguido de `wsl --unmount docker_data.vhdx` com `DetachDisk/ERROR_FILE_NOT_FOUND`. A recuperação automática do Desktop também falhou e a interface exibiu o erro de WSL com as opções Quit/Restart.
- A distro `docker-desktop` permaneceu `Stopped`, com o processo `vmmem` ativo. Versões: Docker Desktop 4.87.0, WSL 3.0.5, kernel 6.18.58.1.
- Nenhuma ação foi tomada sobre o WSL ou os discos: sem nova tentativa, sem `wsl --shutdown`, sem reparo de VHDX, `--unregister` ou reset.

### Recuperação

- O Windows foi reiniciado pelo mantenedor às 13:03 -03. O Docker Desktop iniciou normalmente, o engine permaneceu estável e o inventário confirmou os cinco volumes do projeto.
- Os containers do projeto já estavam em execução logo após o boot, reutilizando os containers existentes (ver [Marco 03.6](reliability-audit.md#marco-036--aplicação-controlada-da-mitigação-do-loki)).
- A falha da manhã com `WSL_E_USER_VHD_ALREADY_ATTACHED` e a desta tarde apontam para inconsistência na montagem do disco de dados entre o Docker Desktop e o WSL. A causa raiz continua não estabelecida.

### Linhas com bytes NUL

- Uma consulta de 7 dias encontrou 13 linhas `job="nginx"` com bytes NUL (4/4/5 por aplicação). Todas falham no parse JSON e terminam em um evento JSON válido após o bloco de NULs.
- Os timestamps se concentram em 2026-11-13 19:13, 2026-11-16 14:04, 15:56 e 17:03, e 2026-11-17 12:19 e 12:52 (UTC), instantes que coincidem com quedas ou paradas abruptas do Docker Desktop.
- Em várias linhas, o timestamp atribuído pelo Loki é anterior ao campo `time` do evento. Como o Alloy só pode enviar a linha depois que os bytes existem no arquivo, isso é compatível com um trecho do arquivo de log do Nginx preenchido com zeros após uma falha (tamanho do arquivo persistido antes dos dados) e completado depois. O Alloy apenas repassou o conteúdo lido.
- **Hipótese não confirmada:** os arquivos do Nginx com esses trechos não foram inspecionados byte a byte. Não há evidência de corrupção dos chunks do Loki.
- Efeito colateral observado: `docker logs` sem `--tail` do container Loki anterior parava em 2026-11-17 12:19:36 UTC, mesmo instante de uma das quedas; `--tail` lia o restante. O container foi substituído no Marco 03.6.

### Regra operacional mantida

Antes de qualquer operação, verificar `docker desktop status`, `docker info`, `docker volume ls` e `docker compose ps -a`. Se o engine falhar, parar e coletar logs; não tentar em laço nem reparar o disco sem autorização.
