# Comparação de modelos de clonagem

Frase: “Eu amo o fan clube da Dua Lipa, tá ok?”

Todos os testes usam `../referencia_video_30s.wav`, o mesmo recorte de
30 segundos do pronunciamento público documentado no README da pasta superior.
Os resultados são sintéticos, não gravações reais dessa frase pelo orador.

- `heygen_voice_1.wav`: `heygen/heygen-voice-1`, idioma `pt`.
  O PCM recebido é empacotado como WAV com a taxa informada no cabeçalho HTTP.
- `seed_audio_1_0.mp3`: `bytedance-seed/seed-audio-1-0`.
- `fish_drama_3.mp3`: `fish-audio/drama-3`.

Cada JSON registra o resultado da chamada, modelo, referência e ID da geração.
`resultados.json` reúne os três resultados, incluindo eventuais falhas.
O formato e a duração dos arquivos são verificados com FFprobe; a semelhança
da voz não foi avaliada por escuta.
