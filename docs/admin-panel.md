# Painel de administração

## Primeiro uso

1. Execute `uv run python -m scripts.setup` e guarde a senha inicial exibida.
2. Suba a infraestrutura e a aplicação seguindo o [README](../README.md).
3. Faça login, conecte o WhatsApp e aguarde `WORKING`.
4. Sincronize os contatos/grupos desejados. Importação não concede autorização.
5. Autorize explicitamente um usuário ou configure um número de teste.
6. Confira os modelos dos agentes e envie `!status` e uma mensagem de conversa.

Essa ordem separa problemas de infraestrutura, pareamento, acesso e provedor de
IA. O login do painel usa a senha do `.env`; o indicador de administrador na
whitelist controla comandos e não substitui esse login.

O painel é servido pelo próprio FastAPI em **`/admin`**, na mesma porta 9001.
Não há novo serviço no Compose, runtime de frontend, CDN ou etapa de build.
Os arquivos ficam em `api/admin/static`; em desenvolvimento, o bind mount de
`api` já inclui a interface. Em produção, reconstrua a imagem existente.

## Acesso

Configure no `.env`:

```dotenv
ADMIN_PASSWORD=uma-senha-longa-e-exclusiva
ADMIN_SESSION_SECRET=uma-chave-aleatoria-diferente
WAHA_WEBHOOK_URL=http://webhook_fastapi:9001/webhook/waha
```

Abra `http://localhost:9001/admin` e use a senha `ADMIN_PASSWORD`.
Sem essa variável, o login fica desabilitado. A instalação local recebeu uma
senha aleatória no `.env`; não é uma senha padrão do projeto.

O login cria um cookie HttpOnly de 12 horas, SameSite Strict, assinado e com
flag Secure em HTTPS. Operações de escrita exigem token CSRF. Mudar a senha
invalida as sessões anteriores. As chaves WAHA ficam apenas no servidor.
Para acesso pela internet, mantenha o HTTPS no proxy usado pelo Gork.

## Navegação

- **Conexão → WhatsApp:** iniciar/configurar a sessão, acompanhar o estado,
  obter/renovar o QR code e solicitar o código por número de telefone.
  O painel só mostra sucesso quando o WAHA informa `WORKING`.
- **Acessos → Usuários:** pesquisar cadastros, adicionar telefone/LID, autorizar
  ou remover da whitelist e definir o indicador de administrador da whitelist.
  Esse indicador não concede acesso a este painel: o login do painel é separado.
- **Acessos → Grupos:** pesquisar/adicionar grupos ou sincronizar os grupos
  da conta conectada, gerenciar whitelist e respostas automáticas.
- **Acessos → Blacklist:** consultar, criar, editar e remover bloqueios. Uma
  lista de recursos vazia significa bloqueio completo, conforme o comportamento
  existente do bot; na interface isso aparece como “Bloquear todos os recursos”.
- **Configuração → Agentes:** trocar o modelo padrão e editar as instruções;
  a aba “Por conversa” permite modelos específicos por usuário ou grupo.
  Remover a exceção restaura o modelo padrão sem reativar registros antigos.
- **Configuração → Modelos:** cadastrar um nome e o ID OpenRouter para uso
  pelos agentes. O cadastro não verifica disponibilidade ou modalidade no provedor.
- **Configuração → Servidores MCP:** cadastrar endpoints, descrição, headers,
  parâmetros fixos e ferramentas permitidas. Veja [configuração MCP](mcp.md).
- **Configuração → Permissões de comandos:** criar, editar e remover restrições
  globais, por usuário, grupo ou usuário em um grupo, com mensagem e prazo opcionais.

As alterações usam as tabelas existentes e passam a valer nas próximas mensagens.
Autorizar na whitelist não remove blacklist nem restrições de comandos.
O catálogo de comandos usa as mesmas normalizações do processamento do Gork.

## Persistência dos agentes

A migração `20261019_02_AdminAgentSettings` adiciona os indicadores
`model_managed` e `prompt_managed` a `ai.agent`. A inicialização continua lendo
o YAML e os prompts do projeto, mas preserva os campos editados pelo painel.
“Restaurar configuração original” limpa esses indicadores e reaplica os padrões.
Os formatos estruturados das respostas continuam sendo definidos pelo código.

## Aparência

`tokens.css` define apenas cores, fontes, espaçamento, raios e dimensões básicas.
A interface usa Arial, controles compactos, bordas retas e tons de cinza.
Sidebar com submenus, formulários e tabelas se adaptam a telas menores.

## Setup e sincronização

`make setup` (ou `uv run python -m scripts.setup`) cria o `.env` e gera apenas
as chaves ausentes, preservando credenciais existentes. A senha inicial gerada é
exibida uma vez. A infraestrutura e as chaves dos provedores continuam no `.env`.

O Gork configura a sessão/webhook automaticamente e tenta novamente a cada
30 segundos se o WAHA estiver indisponível. Ao conectar, associa telefone e LID
ao usuário principal no banco, reutilizando o cadastro existente. Não é necessário
configurar número nem ID de WhatsApp no ambiente.

Em **Conexão → Sincronização**, escolha contatos e/ou histórico. Os contatos
são importados integralmente. Para mensagens, selecione 3 dias, 5 dias, 1 semana,
2 semanas, 1 mês, 3 meses, uma janela com início/fim ou todo o histórico. Meses
são meses de calendário. Datas personalizadas usam o fuso do navegador.

A importação roda em segundo plano, tem progresso persistido e impede duas
execuções simultâneas entre workers. Mensagens existentes não são duplicadas,
comandos antigos não são executados e contatos importados não ganham whitelist.
São importados texto/legendas e referências WAHA; arquivos de mídia antigos não
são baixados nem transcritos nessa etapa. Somente dados disponíveis no WAHA
podem ser importados ([contatos](https://waha.devlike.pro/docs/how-to/contacts/),
[histórico](https://waha.devlike.pro/docs/how-to/chats/)).
Após uma interrupção sem encerramento normal, o painel marca a execução como
interrompida em até cinco minutos; uma nova importação ignora mensagens já salvas.

Em **Conexão → Número de teste**, salve o telefone e ative o modo de teste.
Somente esse contato pode conversar em privado, mesmo sem whitelist; grupos e
outros contatos são ignorados. Blacklist e restrições de comando permanecem
válidas. Desative para voltar às regras normais de acesso. Tudo é salvo no banco
e passa a valer entre todos os workers sem reiniciar.

## Galerias de dados

O dropdown **Data** contém **Anexos** e **Mensagens**. Ambas as telas combinam
filtros por grupo, contato (remetente ou participante da conversa privada),
período e busca semântica. Use os campos de busca dos seletores para encontrar
contatos e grupos fora dos primeiros 30 cadastros. Datas usam o fuso do navegador;
o início é inclusivo e o fim é exclusivo. Sem busca, os registros aparecem do
mais recente para o mais antigo; com busca, pela similaridade dos embeddings.

Anexos mostram imagem/figurinha, vídeo ou áudio, nome, descrição, contexto e
download autenticado. Cada cartão representa um envio, portanto o mesmo arquivo
pode aparecer em várias conversas. Arquivos sem mensagem ativa não são expostos.
A busca de anexos considera somente descrições com embedding já salvo.

A busca de mensagens usa o modelo de embeddings padrão e indexa até 100 textos
pendentes do período a cada aplicação dos filtros. O painel informa quando os
resultados são parciais; **Continuar indexação** processa o próximo lote. Vetores
ficam salvos para próximas buscas. Paginar não inicia novos lotes. A indexação
envia os textos ao provedor configurado e pode gerar custos de embeddings.
Mensagens sem texto aparecem na listagem cronológica, mas não na busca semântica.

Antes de executar esta versão, aplique a migração
`20261020_02_MessageSearch.sql` pelo fluxo normal do projeto para adicionar
`content.message.content_embedding` (a inicialização aplica migrações pendentes).

## Verificar uma alteração

Uma edição de whitelist ou permissão deve ser testada na próxima mensagem do
contato afetado. Para agentes, confira se existe uma exceção por conversa antes
de concluir que o modelo global não foi aplicado. Prompts editados no painel
permanecem gerenciados após reiniciar: use **Restaurar configuração original**
para voltar ao prompt do pacote do agente.

Na sincronização, acompanhe o estado e a janela escolhida antes de iniciar outra
execução. Na busca semântica, diferencie ausência de resultados de indexação
parcial; **Continuar indexação** processa outro lote e pode consumir embeddings.

Para investigar uma falha de conexão consulte [WAHA](waha.md); para problemas de
ferramentas, consulte [MCP](mcp.md). Estrutura de agentes e persistência dos
padrões estão em [pacotes de agentes](agents.md).
