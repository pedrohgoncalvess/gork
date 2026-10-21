# Painel de administração

O painel é servido pelo próprio FastAPI em **`/admin`**, na mesma porta 9001.
Não há novo serviço no Compose, runtime de frontend, CDN ou etapa de build.
Os arquivos ficam em `api/admin/static`; em desenvolvimento, o bind mount de
`api` já inclui a interface. Em produção, reconstrua a imagem existente.

## Acesso

Configure no `.env`:

```dotenv
ADMIN_PASSWORD=uma-senha-longa-e-exclusiva
ADMIN_SESSION_SECRET=uma-chave-aleatoria-diferente
WAHA_WEBHOOK_URL=http://api:9001/webhook/waha
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
A interface usa fontes do sistema, SVGs locais, superfícies claras e verde escuro.
Sidebar com submenus, formulários e tabelas se adaptam a telas menores.
