# Migração para WAHA / GOWS

O Gork usa a mesma imagem base do Orbia:
`devlikeapro/waha:gows-2026.9.1@sha256:d2056b8dec41b218b54f431b8b4eb7d148346d530bb3658295ecb882944e9a18`.
O Dockerfile mantém a preparação de permissões dos volumes do Orbia. Os projetos
têm sessões, mídias e containers separados; o Orbia foi consultado apenas para leitura.

## Configuração

Adicione ao `.env` (use duas chaves aleatórias distintas):

```dotenv
WAHA_BASE_URL=http://waha:3000
WAHA_API_KEY=chave-da-api
WAHA_SESSION=default
WAHA_WEBHOOK_TOKEN=segredo-do-webhook
WHATSAPP_INSTANCE_NUMBER=numero-atual-do-bot
WAHA_PORT=3002
```

Mantenha o mesmo número de WhatsApp cadastrado para o bot no banco.
`EVOLUTION_INSTANCE_NUMBER` ainda é aceito como fallback de identidade na transição.
As demais variáveis `EVOLUTION_*` não são usadas. A sessão `default` funciona com
a imagem Core; use outra sessão somente se a sua edição WAHA permitir.

Desative a instância Evolution antes de conectar o mesmo número no WAHA. Preserve
os volumes antigos para poder voltar. Não apague ou recrie o PostgreSQL ou o MinIO.

```sh
# Desenvolvimento (Postgres, MinIO e Redis já estão no compose)
docker compose -f docker-compose.dev.yaml up -d --build

# A inicialização do Gork aplica a migração de referências WAHA automaticamente.
docker compose -f docker-compose.dev.yaml exec webhook-fastapi python -m scripts.waha_session configure

# Aguarde SCAN_QR_CODE, gere o QR e copie para a máquina local.
docker compose -f docker-compose.dev.yaml exec webhook-fastapi python -m scripts.waha_session status
docker compose -f docker-compose.dev.yaml exec webhook-fastapi python -m scripts.waha_session qr --output /tmp/waha-qr.png
docker compose -f docker-compose.dev.yaml cp webhook-fastapi:/tmp/waha-qr.png ./waha-qr.png
```

Leia o QR com **WhatsApp → Aparelhos conectados** e confirme o estado `WORKING`.
Em produção, use `docker-compose.prod.yaml` e o serviço `api` nos comandos acima;
Postgres e MinIO continuam sendo os serviços externos configurados no `.env`.
O endereço interno do webhook é o mesmo nos dois composes:
`http://webhook_fastapi:9001/webhook/waha`.

Para rodar o script fora do container, use `WAHA_BASE_URL=http://localhost:3002`
no ambiente desse processo. O argumento `--webhook-url` deve continuar apontando
para um endereço acessível pelo container WAHA. A porta local 3002 evita a porta
3001 usada pelo Orbia. `WAHA_IMAGE` e `WAHA_PORT` permitem sobrescrever a imagem
e a porta; hosts ARM precisam de uma imagem GOWS compatível.

## Compatibilidade

- Os eventos `message.any` incluem recebidas e enviadas. Assine apenas esse evento:
  assinar também `message` duplica as mensagens recebidas.
- O webhook verifica `X-Webhook-Token` e a sessão antes de iniciar o processamento.
- O adaptador converte `@c.us`, `@lid`, `Info.SenderAlt`, mensagens temporárias,
  menções, legendas e `replyTo`/`contextInfo` para o contrato dos handlers existentes.
- IDs históricos de mensagens permanecem como stanza IDs. A tabela adicional
  `content.waha_message_reference` guarda o ID completo, chat e URL de mídia do WAHA
  no PostgreSQL, compartilhados entre workers e persistidos após reiniciar.
- Texto, menções e respostas usam os endpoints WAHA. Áudios TTS são convertidos
  para voice notes pelo WAHA. Imagens, vídeos, arquivos e figurinhas estáticas ou
  animadas mantêm as interfaces usadas pelos comandos existentes.
- Comandos, geração de imagens, descrições, embeddings, deduplicação, galerias,
  favoritos, observações, lembretes, filtros, blacklist e consumo continuam nos
  mesmos handlers e repositórios. Imagens e mídias arquivadas continuam no MinIO;
  o volume de mídia WAHA é o cache do provedor, não substitui o armazenamento Gork.
- A sessão WAHA é nova: mídias antigas disponíveis apenas no Evolution, que não
  chegaram ao MinIO, não são migradas por esta alteração. Mantenha os volumes
  Evolution enquanto valida o acervo.

## Validação depois do pareamento

Confira `!status` e `!help` em um privado autorizado; em grupo, mencione o bot e
responda a uma mensagem dele. Envie e cite foto, áudio, vídeo e figurinha; verifique
os vínculos em `content.message`/`content.media` e os objetos no MinIO. Teste
`!image`, `!describe`, `!sticker`, `!gallery`, `!picture`, favoritos e lembretes,
incluindo uma menção enviada pelo bot. Reinicie os serviços e repita uma resposta
com mídia citada para verificar a persistência.

Referências do contrato WAHA: [envio](https://waha.devlike.pro/docs/how-to/send-messages/),
[recebimento](https://waha.devlike.pro/docs/how-to/receive-messages/),
[webhooks](https://waha.devlike.pro/docs/how-to/events/),
[LIDs](https://waha.devlike.pro/docs/how-to/contacts/).
