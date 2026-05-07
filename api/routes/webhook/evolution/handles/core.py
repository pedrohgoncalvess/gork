import re
from datetime import datetime, timedelta


COMMANDS = [
    ("@Gork", "Interação genérica. _[Menção necessária apenas quando em grupos]_", "interaction", []),
    ("!help", "Mostra os comandos disponíveis. _[Ignora o restante da mensagem]_", "utility", []),
    ("!audio", "Envia áudio como forma de resposta. _[Adicione !english para voz em inglês]_", "audio", []),
    ("!resume", "Faz um resumo das últimas 30 mensagens. _[Ignora o restante da mensagem]_", "utility", []),
    ("!search", "Faz uma pesquisa por termo na internet e retorna um resumo.", "search", []),
    ("!model", "Mostra o modelo sendo utilizado.", "search", []),
    ("!picture", "Envia a foto dos usuários mencionados", "image", []),
    (
        "!sticker",
        "Cria um sticker com base em uma imagem e texto fornecido. _[Use | como separador de top/bottom]_ \n_(Obs: Mensagens quotadas com !sticker será criado um sticker da mensagem com a foto de perfil de quem enviou)_",
        "image",
        [
            (":no-background", "Remove fundo da imagem.", [("t", "Verdadeiro"),]),
            (":random", "Usa uma imagem aleatória", [("t", "Verdadeiro"),]),
            (":fill", "Preenche todo o tamanho do sticker cortando o excesso da imagem.", [("true", "Verdadeiro"),]),
            (":url", "Usa uma URL do Twitter/X como fonte do sticker.", [("https://x.com/usuario/status/12345", "Link do post"),]),
            (":effect", "Adiciona um efeito. *Apenas figurinhas animadas*", [
                ("explosion", "Efeito de explosão"),
                ("breathing", "Efeito de respiração (infla e desinfla)"),
                ("rotation", "Efeito de rotação (360 graus)"),
                ("bulge", "Efeito de balão/infla"),
                ("pinch", "Efeito de pinça/implode"),
                ("swirl", "Efeito de redemoinho"),
                ("wave", "Efeito de ondas"),
                ("fisheye", "Efeito olho de peixe"),
            ]),
        ]
    ),
    ("!english", "", "hidden", []),
    ("!remember", "Cria um lembrete para o dia, hora e tópico solicitado. _[Ex: Lembrete para comentar amanhã as 4 da tarde]_", "reminder", []),
    ("!transcribe", "Transcreve um áudio. _[Ignora o restante da mensagem]_", "audio", []),
    ("!image", "Gera ou modifica uma imagem mencionada. _[Mencione alguém para adicionar a foto de perfil ao contexto de criação. Adicione @me na mensagem e sua foto vai ser mencionada no contexto.]_", "image", []),
    ("!consumption", "Gera relatório de consumo de grupos e usuários.", "search", []),
    ("!describe", "Descreve uma imagem.", "image", []),
    ("!gallery", "Lista as imagens enviadas. _[Filtros podem ser feitos com termos ou datas]_", "image", []),
    ("!favorite", "Favorita uma mensagem.", "utility", []),
    ("!list", "", "hidden", []),
    ("!remove", "", "hidden", []),
    ("!twitter", "Baixa vídeos ou imagens de links do X/Twitter e envia. _[Ex: !twitter https://x.com/usuario/status/12345]_", "media", []),
    ("!instagram", "Baixa reels do Instagram e envia. _[Ex: !instagram https://www.instagram.com/reel/XXXXXXXX]_", "media", []),
]

async def is_message_too_old(timestamp: int, max_minutes: int = 20) -> bool:
    created_at = datetime.fromtimestamp(timestamp)
    return created_at < (datetime.now() - timedelta(minutes=max_minutes))


def clean_text(text: str, remove_mentions: bool = True) -> str:
    treated_text = text.strip()
    for command, _, _, _ in COMMANDS:
        treated_text = treated_text.replace(command, "")

    if remove_mentions:
        treated_text = re.compile(r'@\d{6,15}').sub('', treated_text)
    treated_text = re.compile(r'\s*:[a-zA-Z-]+=\S+').sub('', treated_text)
    return treated_text.strip()


def has_explicit_command(text: str) -> bool:
    return any(cmd in text.lower() for cmd, _, _, _ in COMMANDS if cmd.startswith("!"))
