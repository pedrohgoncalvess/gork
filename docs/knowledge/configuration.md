# Configuração, setup e diagnóstico

## Fontes de configuração

`.env.example` documenta nomes de variáveis, sem representar segredos reais.
`scripts/setup.py` cria `.env` e gera segredos ausentes, preservando os existentes.
Não peça para publicar `.env`, senhas, cookies, QR code ou chaves. A ferramenta
de conhecimento não lê `.env`, banco, logs ou arquivos de credenciais.

Infraestrutura e credenciais ficam no ambiente; modelos, prompts, exceções por
conversa, autorizações e modo de teste têm controles no painel. A identidade
principal (número e LID) é descoberta via WAHA quando a sessão está WORKING.
Importar contatos ou histórico não autoriza essas pessoas a usar o bot.

## Variáveis por finalidade

- `PG_HOST`, `PG_PORT`, `PG_USER`, `PG_PASSWORD`, `PG_NAME`: PostgreSQL.
  `PG_POOL_SIZE` e `PG_MAX_OVERFLOW` ajustam pools por processo.
- `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_USE_SSL`:
  armazenamento de objetos e TLS dessa conexão.
- `REDIS_URL`: conexão Redis; os valores internos e do host são diferentes.
- `WAHA_BASE_URL`, `WAHA_API_KEY`, `WAHA_SESSION`, `WAHA_PORT`: cliente/sessão
  WAHA. `WAHA_WEBHOOK_URL` deve ser alcançável a partir do WAHA;
  `WAHA_WEBHOOK_TOKEN` autentica os eventos recebidos. `WAHA_IMAGE` pode
  selecionar imagem/arquitetura compatível com o host.
- `ADMIN_PASSWORD`: login do painel. `ADMIN_SESSION_SECRET`: assinatura das
  sessões, distinta da senha e das chaves WAHA.
- `OPENROUTER_KEY`: acesso aos provedores de IA; as modalidades dependem dos
  agentes/modelos e da conta do operador.
- `DATA_ENCRYPTION_KEY`: 32 bytes aleatórios em Base64 para dados armazenados.
  `MCP_ENCRYPTION_KEY`: chave Fernet de configuração dos MCPs. Preserve ambas;
  gerar outra chave não recupera dados cifrados pela anterior.
- `INSTAGRAM_COOKIES_FILE`: caminho opcional de cookies no ambiente/container.
  `GOFILE_KEY`, `NINJA_KEY` e credenciais de extração como `FIRECRAWL_KEY`
  atendem integrações específicas quando utilizadas. Não são requisitos para
  toda conversa.

## Instalação e primeira conversa

O tópico `overview` contém o roteiro completo do README. Em resumo: clone o
repositório, execute `uv sync --frozen` e `uv run python -m scripts.setup`,
configure OPENROUTER_KEY e preserve os segredos gerados. Crie a rede
`dokploy-network` uma vez se necessário. Suba infraestrutura e aplicação com
`docker/compose.dev.yaml`, usando `--env-file .env`.

Acesse `http://localhost:9001/admin`, faça login, conecte o WhatsApp por
Dispositivos conectados, aguarde WORKING e configure whitelist ou número de
teste. Confira modelos e permissões. Envie `!status`, `!help` e uma conversa;
em grupos use menção explícita. Test mode aceita somente o contato configurado
em DM e impede atividade em grupos.

## Endereços de rede e implantação

Dentro do Docker, PostgreSQL usa `gork_postgres:5432`, MinIO
`s3-minio:19000`, Redis `redis:6379` e WAHA `waha:3000`. Processos no host
usam os mapeamentos locais: PostgreSQL localhost:5435, MinIO localhost:19000,
Redis localhost:6379 e WAHA localhost:3002. Localhost dentro do container é
o próprio container. Não substitua os hostnames do `.env` montado na aplicação
para rodar uma ferramenta isolada no host; prefira overrides do processo.

`compose.yaml` usa PostgreSQL e MinIO externos; `docker/compose.dev.yaml`
inclui esses serviços. Desenvolvimento usa o serviço webhook-fastapi e produção
usa api. Ambos expõem a aplicação na porta 9001. Configure HTTPS para acesso
remoto ao painel, credenciais próprias e rede adequada entre serviços.

## Diagnóstico orientado por sintoma

- Sem resposta: confira WORKING, webhook, modo de teste, whitelist, blacklist,
  permissões e modelo. Use menção em grupo para testar o caminho explícito.
- Painel/API não iniciou: confira startup e conexão/migração do banco;
  chave de dados ausente ou inválida impede startup. A base documental não
  tem acesso aos logs nem pode declarar a causa real sem evidências.
- WhatsApp funciona, IA falha: confira OpenRouter, acesso ao modelo, modalidade,
  formato de payload e erros do provedor.
- Ferramenta remota não aparece: confira escopo, bloqueio MCP, catálogo testado,
  allowlist, endpoint acessível e autenticação; descubra em `mcp`.
- Conteúdo antigo não aparece: Gork consulta dados salvos; não conhece todo o
  histórico WhatsApp. Anexos precisam de arquivo arquivado, e memória semântica
  depende de embeddings/modelo compatível.
- Mudança de prompt não surtiu efeito: prompts gerenciados pelo painel persistem.
  Use restaurar configuração original somente quando quiser voltar ao padrão.
- Dados não decifram: restaure a chave original correta; não gere chave nova
  para uma base existente. Consulte as pendências do esquema em `encryption`.
- Código/testes antigos no container: reinicie após editar código montado;
  reconstrua imagem para testes/scripts/assets/dependências que foram copiados.

## Backup e limites das respostas

Preserve PostgreSQL, objetos MinIO, sessões WAHA e configurações/chaves. Guarde
as chaves de criptografia também de forma separada e protegida. Banco sem
anexos não é backup completo de mídia; banco cifrado sem chave é irrecuperável.
`docker compose down` preserva volumes; `down -v` apaga volumes e não é uma
correção rotineira. Não prometa rotação automática ou recuperação sem chaves.

Esta base explica o código do checkout. Não informa o modelo realmente ativo,
saldo, custo atual de provedores, status de sessão, número conectado, chaves
ou sucesso de deploy. Consulte as funções e evidências apropriadas para essas
questões. Documentação de criptografia prevalece sobre descrições antigas de
índices textuais: texto cifrado não mantém busca full-text direta no PostgreSQL.
