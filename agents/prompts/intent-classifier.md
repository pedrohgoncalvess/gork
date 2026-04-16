Classifique a intenção do usuário em uma das funções abaixo:

FUNÇÕES:
- remember: Agendar lembretes/avisos (ex: "me avisa", "lembra amanhã", "notifica sobre")
- search: Buscar na internet (ex: "pesquisa", "procura", "busca sobre", "qual é")
- image: Criar/editar imagens (ex: "gera imagem", "cria foto", "desenha", "ilustra")
- sticker: Fazer figurinha/sticker (ex: "cria sticker", "faz figurinha")
- transcribe: Transcrever áudio citado (contexto: respondendo áudio quote)
- resume: Resumir histórico da conversa (ex: "resume", "o que falamos", "histórico")
- model: Mostrar IA/modelos usados (ex: "qual modelo", "que IA", "versão")
- help: Listar comandos/ajuda (ex: "ajuda", "comandos", "como usar")
- conversation: Conversa genérica/perguntas

MODIFICADORES (combine com vírgula):
- audio: Resposta deve ser em áudio (ex: "responde em áudio", "manda voz", "fala isso")

Mensagem: {MENSAGEM DO USUARIO}
Informações da última mensagem:
Mensagem de áudio: {SE É UMA MENSAGEM DE AUDIO}
Imagem anexada: {SE TEM UMA IMAGEM ENVIADA}
Quote áudio: {SE TEM UMA MENSAGEM DE AUDIO QUOTADA}
Quote imagem: {SE TEM UMA IMAGEM QUOTADA}

REGRAS:
1. Responda APENAS o nome da função
2. Se quer áudio + outra ação: "função,audio" (ex: "search,audio")
3. Se só quer áudio em conversa: "conversation,audio"
4. **IMPORTANTE: Se "Mensagem de áudio" = Sim OU "Quote áudio" = Sim, SEMPRE retorne "conversation,audio" (responde com áudio também), EXCETO se o usuário pedir explicitamente para NÃO responder em áudio (ex: "transcreve", "escreve", "texto")**
5. Se "Quote áudio" = Sim E usuário pede transcrição explicitamente: "transcribe"
6. Se "Imagem anexada" = Sim E usuário pede análise/edição: considere contexto da mensagem
7. Na dúvida: "conversation"