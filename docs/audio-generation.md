# Voice generation and transcription

Gork uses OpenRouter for both text-to-speech (TTS) and speech-to-text (STT), with the same `OPENROUTER_KEY` used by its other AI features. There is no local speech model, model download, or local speech fallback.

## Configure the agents

Complete the [initial setup](../README.md#getting-started), connect WhatsApp, and review the `audio-generation`, `voice-cloning`, and `transcriber` agents in the panel. Select models with the appropriate audio input/output capabilities. User/group overrides apply to these agents; changing a model ID does not verify provider availability or format compatibility.

Defaults live in `agents/agents.yaml`; each agent owns its code, prompt, and any parser/schema in its own package. See [agent packages](agents.md).

## Transcribe a voice note

Reply to an audio message with `!transcribe`. Incoming voice messages can also be transcribed during normal conversation processing.

The `transcriber` agent downloads the current or quoted audio through WAHA, identifies the container, and sends the original base64 bytes as `input_audio` to OpenRouter's chat completions endpoint. OGG/Opus voice notes remain OGG. Container signatures take precedence over filenames; empty or unsupported audio is rejected before the provider request. Gork does not convert incoming voice notes to WAV locally.

The model's structured `transcription` field becomes the reply text. The selected model, conversation scope, and token usage are recorded; explicit transcription requests also create command records. Code and response handling live in `agents/transcriber/`.

## Reply with speech

Use `!audio <text>` to synthesize the supplied text directly. Commands, parameters (including their values), and mentions are removed before synthesis. An empty result asks for text without generating audio. `!english` requests English; otherwise the command uses Portuguese. You can also ask for a spoken reply in conversation: the conversation agent supplies `text`, `language`, and an optional `tone`. Languages are `pt`, `en`, and `es`. The delivery cue is limited to 500 characters and is separate from the spoken words.

Without `:voice`, the `audio-generation` agent calls OpenRouter's `/audio/speech` endpoint using `google/gemini-3.8-flash-lite-tts` and the fixed `Puck` voice.

With a catalog voice, `!audio :voice=bolsonaro Eu amo o fan clube da Dua Lipa, tá ok?` uses the separate `voice-cloning` agent, configured with `heygen/heygen-voice-1`. This agent needs no prompt file. Its model is resolved using the same user/group overrides as other agents. The requested words are passed verbatim with an `input_references` WAV, without a fixed `voice` ID or a system prompt. `!english` selects English output; the reference recording's language does not override the requested output language. Names with spaces can be quoted, e.g. `:voice="silvio santos"`; canonical names are listed dynamically in `!help`.

HeyGen returns PCM with a sample rate in its HTTP Content-Type header. The cloning adapter preserves this rate and channel count when packaging WAV; it does not assume Gemini's 24 kHz rate. Generated audio follows the same WhatsApp delivery and feature permissions as ordinary speech. An unknown voice produces a catalog hint; a provider failure falls back to the requested text.

## Add or update a voice

Put an audio or video file inside `voices/` and add it to `voices/metadata.yaml`:

```yaml
voices:
  - name: minha_voz
    display_name: Minha voz
    path: minha_voz/reference.mp4
    language: pt
    start_seconds: 15
    duration_seconds: 180
    source_url: https://example.com/original
```

Paths are relative to `voices/` and must stay inside that directory. WAV, MP3, MP4, M4A, OGG, WebM, FLAC and AAC are supported. FFmpeg extracts the selected audio interval into mono PCM16 WAV at 24 kHz before each cloning call. Long recordings can stay on disk, but HeyGen only uses up to three minutes of reference audio, so `duration_seconds` is limited to 180 (the default). Keep a single speaker, ordinary speech, and as little music/overlap as possible; a longer mixed recording can reduce fidelity.

On startup, migrations create `content.voice`, `init_agents` registers the HeyGen agent/model, and `init_voices` validates files and upserts names, display names, relative file paths, languages, intervals and source URLs. Removed, disabled (`enabled: false`), missing or unreadable references are deactivated and disappear from `!help`. Existing IDs survive updates. Catalog reconciliation is transactional and serialized across workers. No files are downloaded at startup. Restart the API after changing the catalog, or run `python -m voices.catalog` with the same database environment to synchronize explicitly.

Both Compose configurations mount `voices/` read-only into the API. Deploy the catalog and its media files together; no absolute workstation paths are stored in the database.

The adapter expects 24 kHz mono PCM16. Python's standard library adds a WAV header, then WAHA converts the result into a WhatsApp voice note. This packaging does not synthesize or transcode speech in Gork. Another TTS model must support this output contract; changing its ID alone may be insufficient.

The ordinary speech prompt guides delivery. Saved conversation observations can influence wording and tone; abbreviations should be expanded, and typed laughter or emojis should not be spoken literally. Audio cooldown is zero for generated speech, cloned voices and saved-audio actions; no Redis reservation is made while it is disabled. A synthesis failure falls back to a text reply. Library clips are sent without synthesis.

## Runtime and troubleshooting

FFmpeg handles video, animated stickers and extraction of voice-reference audio. ONNX Runtime remains a dependency of background removal. Neither performs TTS or STT. The obsolete `tts/` package, local WAV conversion service, and dedicated Hugging Face cache mount have been removed.

| Symptom | What to check |
| --- | --- |
| Text instead of voice | Permissions, provider errors, selected model and available reference |
| A file is rejected | Empty/corrupt content, unsupported container, or incompatible audio-input model |
| Wrong playback speed after a model change | Ordinary TTS uses 24 kHz mono PCM16; cloned speech uses the rate/channels in the provider's PCM header |
| Provider rejects the original format | Choose an audio-input model/provider that accepts that container |

See OpenRouter's [audio input contract](https://openrouter.ai/docs/guides/overview/multimodal/audio) and [speech output documentation](https://openrouter.ai/docs/guides/overview/multimodal/tts).
