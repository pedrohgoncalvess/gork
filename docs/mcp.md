# MCPs no Gork

## Exemplo de uso

Um servidor de documentação pode oferecer `search_documents`. Cadastre seu
endpoint, descreva quando consultá-lo e salve a autenticação nos headers fixos.
Se o servidor exigir um tenant, configure `tenant_id` como argumento fixo da
ferramenta. O modelo pode escolher o texto da busca, mas não trocar esse tenant.

Primeiro use **Testar** para confirmar a descoberta do catálogo. Depois peça ao
Gork, em uma conversa autorizada, uma informação que exija consultar os documentos.
Confira no histórico se a ferramenta foi chamada: descobrir o catálogo não
executa a ferramenta e não garante que o modelo a escolherá em todo pedido.

O painel **Configuração → Servidores MCP** cadastra múltiplos servidores remotos.
Os clientes rodam no processo FastAPI existente. Não há serviço novo no Compose.

## Configurar

1. Defina `MCP_ENCRYPTION_KEY` no `.env`. A instalação local já recebeu uma chave.
   Em outro ambiente, gere uma chave Fernet e mantenha-a junto dos segredos do Gork:

   ```sh
   uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

2. Reconstrua/inicie o Gork. A migração adiciona `ai.mcp_server` e `ai.mcp_call`.
3. No painel, adicione o nome, a descrição e a URL completa do endpoint MCP.
   A descrição explica ao modelo o que consultar e em quais situações usar o serviço.
4. Escolha **Streamable HTTP** ou **SSE (legado)**. O SDK oficial negocia o
   protocolo HTTP e mantém o ciclo de conexão de cada chamada.
5. Preencha headers e parâmetros fixos quando necessário. Salve e clique em
   **Testar** para buscar o catálogo. Esse teste não executa ferramentas de negócio.

Use URLs acessíveis de dentro do container Gork. Para outro serviço na mesma
rede Docker, use seu hostname de serviço. `localhost` aponta para o próprio
container, não para a máquina que executa Docker.

### Headers fixos

```json
{"Authorization": "Bearer sua-chave", "X-Workspace": "equipe"}
```

São enviados nas requisições MCP pelo cliente. O modelo não recebe esses valores
nem pode defini-los. Headers reservados pelo transporte não são aceitos.

### Parâmetros fixos da conexão

```json
{"workspace_id": "123", "locale": "pt-BR"}
```

São parâmetros de query da URL. Valores configurados têm prioridade sobre os
mesmos parâmetros já presentes na URL. Também são aplicados ao endpoint POST
anunciado pelo SSE, preservando o identificador de sessão gerado pelo protocolo.
Não há interpolação de variáveis nem preenchimento desses campos pelo modelo.

### Argumentos fixos por ferramenta

```json
{
  "search_documents": {
    "tenant_id": "empresa-123",
    "limit": 10,
    "filters": {"visibility": "internal"}
  }
}
```

As chaves são os **nomes originais** das ferramentas no servidor MCP.
Esses argumentos são mesclados no servidor, recursivamente, com prioridade
sobre os argumentos sugeridos pelo modelo. O modelo ainda pode preencher
outros campos, como `query`, mas não pode sobrescrever `tenant_id`, `limit`
ou `filters.visibility`. Os campos fixos são removidos do schema anunciado
ao modelo. O conjunto final é validado contra o JSON Schema da ferramenta.

## Disponibilidade e permissões

- Cada MCP pode atender todos os autorizados, um usuário no privado ou um grupo.
  Um MCP privado de usuário não fica disponível nas conversas de grupo.
- A lista de ferramentas permitidas aceita um nome original por linha. Vazia,
  disponibiliza todas as ferramentas descobertas. O catálogo é atualizado pelo teste.
- Desabilitar/remover um servidor interrompe novas chamadas. O estado e o escopo
  são verificados novamente antes da execução.
- Whitelist e controles existentes continuam valendo. O recurso **Consultas MCP**
  também pode ser bloqueado pela blacklist ou pelas permissões de comandos.
- Alterar URL, transporte, headers ou parâmetros invalida o catálogo. É necessário
  testar de novo antes de disponibilizar as ferramentas dessa conexão.

## Execução pelo agente

Os agentes de conversa recebem ferramentas nativas no campo `tools` da API de
completions. O modelo decide quando consultar e emite `tool_calls`; o Gork resolve
o alias estável, chama `tools/call` no servidor correspondente com o nome original
e devolve o resultado como mensagem `role: tool`. A resposta final continua usando
o JSON de ações do Gork. Um turno pode consultar ferramentas de vários MCPs.

O modelo escolhido para o agente precisa suportar tool calling. Recursos
especializados, como geração de imagem e áudio, mantêm seus fluxos anteriores.

Cada chamada verifica o schema atual no servidor. Referências de JSON Schema
externas não são buscadas. Falhas viram resultados de erro para o modelo, sem
inventar dados. Textos e `structuredContent` entram no contexto; blocos binários
de áudio/imagem não são encaminhados por esse fluxo de consulta.

Há um limite de 128 ferramentas anunciadas por execução, incluindo uma vaga
reservada à [base de conhecimento local do Gork](knowledge/README.md) e até 127
ferramentas remotas, 6 rodadas, 12 chamadas e 60 segundos acumulados em consultas.
Chamadas idênticas no mesmo turno
reutilizam o resultado. Não há repetição automática de operações de negócio.
O timeout por MCP é configurável de 3 a 60 segundos. As rodadas do modelo têm
seus tokens e custo registrados pelo fluxo de consumo existente.

## Armazenamento

Headers, parâmetros de conexão e argumentos fixos ficam cifrados com Fernet no
PostgreSQL. Preserve a chave: trocar `MCP_ENCRYPTION_KEY` sem migrar as configurações
impede a leitura dos valores existentes. Ela é independente da senha do painel.

A listagem administrativa não retorna os segredos. A edição autenticada pode
ler os valores para alterá-los. O histórico de chamadas armazena apenas servidor,
nome original da ferramenta, usuário/grupo, mensagem, duração e sucesso. Headers
e argumentos não são gravados nesse histórico. Logs de completions omitem conteúdo
das respostas de ferramentas e argumentos das chamadas.

OAuth interativo, servidores locais por comando/stdio, prompts e recursos MCP
não são configurados neste painel; a integração expõe ferramentas dos endpoints
HTTP/SSE e usa autenticação determinística por headers/parâmetros.

## Quando uma ferramenta não aparece ou falha

Confira se o servidor está habilitado e permitido para o usuário/grupo atual,
se o nome está na lista de ferramentas permitidas e se a URL é acessível de
dentro do container. Um endpoint local à máquina do desenvolvedor não é o
`localhost` do container Gork.

Falhas de catálogo costumam envolver URL, transporte, autenticação ou timeout.
Falhas de execução também podem vir do schema ou dos argumentos fixos. O teste
do painel não valida uma operação de negócio. Consulte o histórico de chamadas
para separar falha do servidor, limite de execução e uma decisão do modelo de
não chamar a ferramenta.

Preserve `MCP_ENCRYPTION_KEY` ao mover o ambiente. Uma senha nova de painel não
substitui a chave necessária para ler headers e parâmetros já cifrados.
