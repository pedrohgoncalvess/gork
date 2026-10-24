# Como o código do Gork funciona

## Entrada e ciclo de vida

`main.py` cria o FastAPI, registra webhook WAHA, rotas administrativas e MCP,
e serve os arquivos estáticos de `/admin/assets`. No startup, valida a chave de
criptografia, aplica migrações, inicializa agentes, preços de modelos, mídia
embutida e lembretes. Depois agenda apuração de votações a cada 5 segundos e
configuração/descoberta automática WAHA a cada 30 segundos. No encerramento,
para o scheduler, cancela tarefas de sincronização e fecha o engine do banco.

## Caminho de uma mensagem WhatsApp

O WAHA recebe eventos do WhatsApp e faz POST no webhook `/webhook/waha`.
`api/routes/webhook/waha/` normaliza identificadores, remetente, mensagens
citadas e mídia. Autorizações, modo de teste, blacklist, restrições de comandos
e moderação condicionam o processamento. O snapshot Redis permite exclusão
rápida de mensagens de membros com ban ativo, com fallback PostgreSQL.

O dispatch de comandos fica em `processors/common.py`, e os handlers em
`handles/`, dentro do pacote WAHA. `handles/core.py` mantém `COMMANDS`, usado
no help. Comandos explícitos de mídia e moderação têm caminhos próprios;
nem todo comando passa pelo agente de conversa.

Mensagens e referências são persistidas por repositórios. Arquivos arquivados
vão para MinIO; a disponibilidade de mídia antiga depende de ela ter sido
salva, não somente da existência de uma linha no banco. Serviços de descrição,
transcrição e embeddings enriquecem o contexto conforme o fluxo.

## Conversas privadas e grupos

`agents/conversation.py` escolhe o agente DM ou grupo. Os entry points em
`agents/conversation_dm/` e `agents/conversation_group/` delegam ao motor em
`agents/_shared/conversation.py`. O motor resolve o agente e o modelo configurado,
monta mensagens do provedor e registra consumo em cada resposta.

O contexto privado usa até 40 mensagens da conversa. Grupos carregam até 50
mensagens recentes e uma cadeia de respostas com até 8 ancestrais, incluindo
mensagens citadas fora da janela recente quando disponíveis. O envelope
CURRENT_MESSAGE identifica o autor e a mensagem atual para evitar confusão
com conversas paralelas. As descrições de mídia podem entrar como texto;
descrição ausente não permite adivinhar o conteúdo de um anexo.

Grupos também podem usar buffer e agente filter para respostas automáticas.
Locks serializam trabalho conversacional; não significam que o bot responde
a cada mensagem. Menção explícita ajuda a diferenciar filtro de indisponibilidade.

## Duas formas de consultar ferramentas

`services/mcp_runtime.py` conduz tool calls nativas do provedor. Anuncia
`consult_gork_knowledge` local e ferramentas de MCPs remotos permitidos no
escopo. A ferramenta local lê somente documentos públicos permitidos. O
conteúdo completo da base não é incorporado ao system prompt; somente descrição,
schema e instrução curta são enviados antes de uma consulta.

Uma chamada nativa devolve uma mensagem `role: tool`, correlacionada por ID.
Chamadas repetidas com os mesmos argumentos no mesmo ciclo reutilizam resultado.
O ciclo compartilha limites de 6 rodadas, 12 chamadas e 60 segundos de execução
de ferramentas. O catálogo comporta 128 ferramentas no total: uma local e até
127 remotas. As respostas do modelo em cada rodada entram no consumo normal.

Separadamente, o contrato JSON de conversa contém `queries`, `actions` e
`next_call_instruction`. `agents/_shared/conversation_parser.py` e os handlers
processam esse plano; `llm_access/` consulta mensagens, usuários, imagens e
observações. Escopos de conversa vêm do backend. A base de conhecimento deve
ser chamada como ferramenta nativa, não como um query_type inventado.

## Saída e execução de ações

Depois das consultas, o modelo retorna o JSON de ações: texto, áudio, imagens,
vídeos, figurinhas, lembretes e outras funções previstas no parser. Handlers
validam parâmetros/permissões e usam agentes especializados ou clientes externos.
O transporte WAHA entrega a mensagem/mídia ao WhatsApp. Um plano do modelo ou
um resultado documental não prova que uma ação foi executada com sucesso.

## Camadas do repositório

- `api/`: endpoints, comandos, painel e autenticação.
- `agents/`: execução, prompts, schemas e parsers de cada agente.
- `external/`: clientes WAHA, OpenRouter, MCP e outras integrações.
- `database/models/`, `database/operations/`, `database/migrations/`: modelos,
  repositórios e evolução do esquema.
- `security/`: envelopes autenticados, tipos SQLAlchemy, JSON, busca e arquivos.
- `services/`: contexto, mídia, memória, moderação, configuração e ferramentas.
- `embeddings/`, `llm_access/`, `s3/`, `scheduler/`: busca vetorial, acesso do
  agente a dados, objetos e jobs.
- `assets/`, `docker/`, `scripts/`, `tests/`, `docs/`: recursos, execução,
  manutenção, verificação e guias.

## Dados, privacidade e configuração

PostgreSQL mantém relações, mensagens, agentes, lembretes, observações e consumo.
pgvector permite busca semântica; MinIO mantém bytes dos anexos e Redis mantém
estado temporário compartilhado. Conversas e documentos não são a mesma base:
observações são dados específicos da conversa, enquanto conhecimento do projeto
é documentação comum e somente leitura.

Prompts/modelos alterados no painel são preservados pelos indicadores
prompt_managed e model_managed. A instrução de consulta ao conhecimento é
injetada pelo runtime mesmo para prompts personalizados já salvos. Não modifica
esses prompts no banco. Schemas continuam definidos pelo código.
