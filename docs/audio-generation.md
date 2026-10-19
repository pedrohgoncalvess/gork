# Geração de voz

Respostas com a ação `audio` usam o agente `audio-generation`, registrado em
`agents/agents.yaml`, pelo endpoint `/api/v1/audio/speech` do OpenRouter. O modelo
padrão é `google/gemini-3.8-flash-lite-tts`; o prompt de fala fica em
`agents/prompts/audio-generation.md`. A chave é a mesma `OPENROUTER_KEY` já usada
pelo restante do projeto.

A voz é sempre `Puck`, definida no backend, inclusive ao falar português,
inglês ou espanhol. A ação recebe `text`, `language` e, opcionalmente, `tone`
(até 500 caracteres). O tom descreve a entrega e segue separado do texto falado;
parâmetros de voz
enviados pelo agente de conversa não alteram o locutor. A saída PCM16 de 24 kHz
é empacotada em WAV pela biblioteca padrão do Python e enviada como nota de voz
pela Evolution API. O cooldown existente de três minutos segue
valendo para `audio` e `send_audio`. Os áudios prontos da biblioteca continuam
sendo enviados sem síntese.

O agente de conversa usa o contexto atual e observações salvas com o prefixo
`Estilo de conversa:` para escolher vocabulário, ritmo, humor e formato da
resposta. O texto falado deve expandir abreviações de chat (`vc` → `você`,
`tbm` → `também`, `pq` → `porque`/`por que`) e não incluir risadas digitadas,
emojis ou instruções de atuação. Isso preserva o tom informal sem ler letras
isoladas. A descrição curta de tom vai em `speech_metadata.style` junto com as
instruções do agente; não altera a voz fixa.

O Piper e o SoundFile foram removidos das dependências. Não é necessário baixar
modelos ONNX de voz. FFmpeg continua necessário para mídias e para converter os
áudios recebidos em WAV antes da transcrição no OpenRouter. `rembg[cpu]` mantém
seu próprio ONNX Runtime para remover fundos de figurinhas.

Após atualizar, execute `uv sync --frozen` e reinicie a aplicação para registrar
o agente. Em Docker, reconstrua a imagem para aplicar o lockfile atualizado.

Referência: https://openrouter.ai/docs/guides/overview/multimodal/tts
