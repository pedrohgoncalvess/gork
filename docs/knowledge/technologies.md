# Tecnologias e responsabilidades

## Aplicação e execução

O projeto requer Python >= 3.13 (`pyproject.toml`), usa uv e `uv.lock` para
dependências, FastAPI para HTTP, Uvicorn/Gunicorn para servir a aplicação,
asyncio para concorrência e APScheduler para jobs. Docker e Compose organizam
os serviços. A imagem Python slim instala FFmpeg e fontes Noto Color Emoji.
As versões efetivamente resolvidas estão no lockfile; os limites mínimos do
pyproject não comprovam versões de uma instalação em execução.

## WhatsApp e inteligência artificial

WAHA com engine GOWS fornece sessão, pareamento, eventos, envio e exclusão de
mensagens. O Gork usa seu cliente HTTP; não é cliente oficial da Meta Cloud API.
OpenRouter roteia as chamadas aos modelos configurados, incluindo conversa,
imagem, vídeo, áudio e embeddings conforme suporte do modelo/provedor.
`httpx` atende chamadas HTTP. Modelo padrão, disponibilidade e preço podem
mudar; use `!model` e o painel para a configuração atual.

O SDK `mcp` conecta ferramentas remotas por Streamable HTTP ou SSE. Não é
necessário um servidor MCP para a base de conhecimento embutida. `jsonschema`
valida argumentos; YAML configura agentes e metadados; os agentes de conversa
produzem JSON estruturado que o backend interpreta.

## Banco, objetos e cache

PostgreSQL guarda dados relacionais; SQLAlchemy implementa modelos e
repositórios, asyncpg é usado no acesso assíncrono e psycopg aparece nos fluxos
de administração/migração. yoyo-migrations mantém migrações. pgvector permite
embeddings e similaridade. Extensões e índices necessários dependem das
migrações. Embeddings são representações numéricas, não versões cifradas do texto.

MinIO fornece armazenamento S3 para anexos, imagens e outros arquivos. Redis
coordena caches e controles entre workers. Esses serviços têm suas próprias
credenciais, volumes, conectividade e responsabilidades de backup.

## Processamento de mídia

Pillow compõe e manipula imagens; imagehash ajuda na deduplicação perceptual.
rembg com runtime CPU remove fundos localmente. FFmpeg processa vídeo e
figurinhas animadas. yt-dlp ajuda em downloads de mídia, e extração de páginas
pode usar trafilatura/Firecrawl conforme o fluxo e credenciais configuradas.
Geração criativa e descrição de mídia dependem dos agentes/provedores.

TTS e STT usam OpenRouter; não há síntese/transcrição local de fallback.
O adaptador de voz embala PCM16 mono de 24 kHz em WAV usando Python e envia
ao WAHA. A presença de FFmpeg ou ONNX não significa que eles geram a fala.

## Segurança e interface

`cryptography` fornece AES-GCM, AES-SIV, HKDF e Fernet. DATA_ENCRYPTION_KEY
protege os dados da aplicação; MCP_ENCRYPTION_KEY protege configurações de
conexões MCP com Fernet. São chaves de finalidades distintas e devem ser
preservadas. Consulte `encryption` para cobertura e ressalvas de implantação.

O painel usa HTML/CSS/JavaScript estáticos no FastAPI, sem serviço separado de
frontend ou build Node obrigatório. O login usa cookie assinado, HttpOnly,
SameSite Strict, Secure em HTTPS e proteção CSRF nas escritas. Whitelist admin
de comandos e autenticação do painel são controles diferentes.
