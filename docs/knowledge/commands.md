# Funções e comandos do Gork

## Como usar

Em DM autorizada, converse diretamente; em grupos autorizados, mencione Gork
ou responda uma mensagem dele. Respostas automáticas dependem de configuração.
Pedidos naturais podem virar ações pelo agente: pedir uma imagem, áudio,
figurinha, vídeo, lembrete ou pesquisa não exige sempre escrever um comando.
O agente escolhe ações suportadas, e o backend aplica permissões e validações.

`!help` mostra o catálogo mantido em `api/routes/webhook/waha/handles/core.py`.
Parâmetros nomeados geralmente aceitam espaço ou `=`, como `:quality 720` e
`:quality=720`. Uma menção precisa ser a menção do WhatsApp, não apenas um nome
digitado. Recursos podem depender de modelos, arquivos, credenciais e permissões.

## Conversa, informação e organização

| Comando | Função e exemplo |
| --- | --- |
| `!help` | Mostra os comandos e opções; ignora o resto da mensagem. |
| `!status` | Verifica disponibilidade pelo caminho do comando. |
| `!model` | Informa o modelo resolvido para a conversa. |
| `!search <termo>` | Pesquisa na internet e resume; não é pesquisa de mensagens privadas. |
| `!resume` | Resume mensagens recentes salvas; há cooldown de duas horas. |
| `!remember <pedido>` | Agenda lembrete, por exemplo `!remember amanhã às 16h confirmar reserva`. |
| `!usage` | Relatório de uso e consumo registrado. |
| `!favorite` | Responda uma mensagem para favoritá-la. |
| `!list` / `!remove` | Opções auxiliares de favoritos; siga `!help` e o retorno do comando. |
| `!gallery [filtro]` | Procura imagens salvas por termos ou datas. |

O handler de resumo carrega até 100 mensagens; a descrição histórica do help
pode mencionar 30. O guia de conversas e o comportamento do handler explicam
a implementação. Não prometa que um resumo inclui todas as mensagens visíveis
no WhatsApp ou todo o histórico anterior à instalação.

`!usage :when 7d :granularity d` agrupa sete dias por dia. `:when` aceita dias
(d), semanas (w) e meses (m); `:granularity` aceita d/w/m e o padrão é dia.
Em grupo, `:user "Maria Silva"` filtra pelo nome ou parte dele. São registros
do Gork e estimativas por preços registrados, não uma fatura do provedor.

## Áudio e transcrição

`!audio <pedido>` solicita resposta falada. `!english` é modificador para voz
em inglês. `!transcribe` respondendo um áudio transcreve o conteúdo; áudios
recebidos também podem entrar no fluxo de conversa. Voz suporta pt/en/es,
usa modelo OpenRouter e uma voz fixa do adaptador. Ações de áudio têm cooldown
de três minutos. Falha de síntese pode retornar texto. Veja o tópico `audio`.

## Fotos e criação visual

- `!image <descrição>`: gera imagem; anexe ou cite uma foto para editar.
  Menções adicionam fotos de perfil como referência, incluindo `@me`.
- `!describe`: descreve imagem anexada/citada, quando disponível.
- `!picture @usuário`: envia foto de perfil salva dos usuários mencionados.
- `!deactivate @usuário`: aplica cinza e rodapé “Deactivated account”. Pode
  responder uma foto; sem fonte/menção, usa foto aleatória conforme o handler.
- `!video <descrição> :duration 5 :quality 720 :audio t`: cria vídeo com opções.
  Duração padrão 5 segundos, máximo 10. Áudio desligado por padrão; qualidade
  padrão é a menor suportada pelo modelo (480/720/1080/2k/4k quando suportadas).
  Mídia anexada/citada e fotos de mencionados podem fornecer referências.
- `!philo :quote socrates`: compõe uma frase com imagem de filósofo. As opções
  do catálogo são socrates, platao, aristoteles, nietzsche e tales_mileto;
  omitir a opção permite seleção aleatória.

Arquivos inexistentes, perfis privados e capacidades do modelo podem impedir
uma ação. Um pedido sobre foto antiga deve citar/anexar a foto correta;
não presumir identidade ou conteúdo de imagens não disponíveis.

## Figurinhas e seus parâmetros

`!sticker legenda superior | legenda inferior` cria figurinha com mídia
anexada/citada. Citar texto pode produzir um cartão com foto do autor e sua
mensagem. O agente também pode selecionar uma mensagem pelo ID disponível ou
usar a ação generate_sticker para uma cena nova com legenda.

| Parâmetro | Comportamento |
| --- | --- |
| `:no-background t` | Remove fundo localmente. |
| `:no-color t` | Converte para preto e branco. |
| `:random t` | Usa uma imagem aleatória. |
| `:fill true` | Preenche recortando excedente; centro é o padrão. |
| `:direction top` | Preserva região: top, bottom, left, right, top-left, top-right, bottom-left ou bottom-right. |
| `:url <url-X>` | Usa mídia de post X/Twitter. |
| `:text t` | Usa texto do post como legenda. |
| `:tweet <url-X>` | Renderiza cartão com autor/avatar/texto e primeira prévia de mídia, quando disponível. |
| `:effect rotation` | Anima/aplica efeito. |
| `:cut 1:00-1:05` | Recorta intervalo de vídeo; também aceita segundos e intervalos abertos como `43-` ou `-46`. |
| `:speed 2` | Ajusta velocidade; em rotation define voltas e em explosion repetições. |
| `:size 0.5` | Multiplica área de bulge/explosão; padrão 1, faixa 0.1 a 3. |
| `:duration 2` | Duração de explosion, 0.1 a 7 segundos; respeita limites do recorte/mídia. |
| `:blur 50` | Desfoque de 0 a 100. |
| `:resize t` | Redimensiona preservando proporção. |
| `:dead t` | Lápide com foto e texto da mensagem citada. |

Efeitos do catálogo: explosion, nuclear-bomb, breathing, rotation, bulge,
pinch, swirl, wave e fisheye. `:duration` de explosion usa 3 segundos para
imagem e até 6 para vídeo por padrão. FFmpeg atende animações; rembg remove
fundos. A criação de uma imagem nova depende do provedor de IA.

## Downloads

`!twitter <url>` baixa vídeo ou primeira imagem de post X/Twitter.
`!instagram <url-reel>` baixa reel; alguns casos precisam de cookie opcional
configurado pelo operador. Conteúdo removido, privado ou bloqueado na origem
pode falhar. A ferramenta de conhecimento explica a função, mas não faz download.

## Moderação

`!ban @usuário :time 30min :expiration 5` abre votação de ban temporário.
`:time` aceita minutos numéricos, sufixos min/hr e horas:minutos; padrão 30,
mínimo 1 e máximo 180 minutos. `:expiration` é o prazo da enquete em minutos,
mínimo 5, padrão 10 e máximo 20. São durações diferentes.

Exige Gork admin. Quórum: ao menos um terço dos membros sem Gork, arredondado
para cima, e mínimo de três votantes. Com quórum, maioria aprova; empate não.
O ban apaga mensagens novas enquanto ativo; não expulsa o membro nem bloqueia
o envio no cliente WhatsApp. Cooldown, apuração, votos e cancelamento estão no
tópico `moderation`. Modo de teste impede moderação em grupos.

## Funções que não são comandos

O painel `/admin` gerencia pareamento WhatsApp, usuários/grupos, whitelist,
blacklist, permissões, agentes/modelos por conversa, sincronização, navegação
de mensagens/anexos, bans e MCPs. Notas de memória podem ser salvas/buscadas
pelo agente no escopo da conversa; não são lembretes agendados.

Ferramentas MCP acrescentam operações de serviços configurados. A ferramenta
`consult_gork_knowledge` consulta documentação do projeto. Ela não executa os
comandos descritos, concede acesso, muda configurações ou verifica status real.
