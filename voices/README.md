# Voice references

`metadata.yaml` is the source of truth for available voice-cloning references.
The API synchronizes it into `content.voice` on every startup; `!help` reads the
active database catalog rather than a hardcoded list. No download runs at startup.

To add a voice, put a media file in this directory (subdirectories are supported)
and append an entry:

```yaml
  - name: minha_voz
    display_name: Minha voz
    path: minha_voz/reference.mp4
    language: pt
    start_seconds: 0
    duration_seconds: 180
    source_url: https://example.com/original
```

Then restart the API, or run `python -m voices.catalog` using its database
environment. Files and paths are validated before a voice becomes available.
Removed, disabled (`enabled: false`), missing and unreadable references are
deactivated. Existing rows are updated without changing their IDs.

Use `!audio :voice=minha_voz Texto para falar`. Without `:voice`, ordinary TTS
continues using the `audio-generation` agent. Cloning uses the promptless
`voice-cloning` agent and its configured HeyGen model.

Supported inputs: MP4, M4A, MP3, WAV, OGG, WebM, FLAC and AAC. Paths are relative
to this directory and cannot escape it. `start_seconds` defaults to 0 and
`duration_seconds` to 180. FFmpeg extracts mono PCM16 WAV at 24 kHz from that
interval. Keep 4–5 minute sources if useful, but HeyGen only uses a maximum
of 3 minutes per request. Shorter references are used at their actual length.

Reference provenance is recorded in YAML and the per-voice `source.json` files.
These are real source recordings; `bolsonaro/clone*` and
`bolsonaro/comparacao_modelos/` are synthetic experiments and are not cataloged
as reference voices. Some television/cartoon sources contain music and other
speakers; their fidelity is provisional, and longer sources do not guarantee a
better clone. Prefer a clean recording of just one speaker when replacing them.
Source attribution does not imply endorsement. License claims by archive
uploaders have not been independently verified.

For deployment, ship this folder with its media. Both Compose files mount it
read-only at `/app/voices`; database paths remain portable between machines.
See `docs/audio-generation.md` for runtime behavior and troubleshooting.
