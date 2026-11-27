# Images, video, stickers, and saved media

## Automatic descriptions and semantic search

New videos, GIFs received as images or videos, and animated WebP stickers get a
Portuguese description through the `describe-video` agent, using
`google/gemini-2.5-flash-lite`. Descriptions and their embeddings are stored in
`content.media.description` and `description_embedding`, so the existing semantic
gallery search can find them. Exact duplicate files reuse the existing record.
Existing media are not backfilled.

Only media lasting at most **60 seconds** (inclusive) and at most **20 MiB** are
submitted. Longer media, unknown durations, and processing/provider failures still
allow the original file to be saved, without a new description. GIF/WebP duration
is one play of the animation, ignoring infinite looping. FFmpeg/FFprobe must be
installed. A temporary MP4 copy is resized to at most 512px per side, retaining
audio when present; the original stored file is unchanged. Inference uses a
private base64 video input and at most 400 output tokens. Usage is recorded as an
agent interaction. Run the normal agent initialization on deployment to register
`describe-video`.

Cost estimate (prices checked 2026-11-09): Flash-Lite costs $0.10 per million
text/image/video input tokens and $0.40 per million output tokens; audio input is
$0.30 per million. At approximately 263 video tokens/second and 32 audio
tokens/second, a 60-second clip with audio, a 200-token prompt and 400-token output
costs about **$0.00234**, or **$2.34 per 1,000 clips**. A silent 60-second clip is
about **$0.00176**. These are estimates; actual tokenization/provider charges
vary. Embeddings use the existing configured embedding model and are extra.

Sources: [OpenRouter pricing](https://openrouter.ai/google/gemini-2.5-flash-lite/pricing),
[Google pricing](https://ai.google.dev/gemini-api/docs/pricing),
[Google token counting](https://firebase.google.com/docs/ai-logic/count-tokens).

## Finding and forwarding stored media

Conversation agents have a native `search_media` tool with `query`, optional
`media_type` (`audio`, `image`, `video`, `sticker`), `mode` (`hybrid`, `semantic`,
`text`) and `limit` (1–10). Hybrid search merges cosine similarity of stored
descriptions with accent-insensitive character similarity over names,
descriptions and audio transcripts. Text matching runs after decryption in the
application, since encrypted fields cannot use SQL trigram matching. It remains
available when embeddings are unavailable. Scores are relevance signals, not
probabilities. The agent must assess the actual description and clarify weak or
ambiguous matches rather than forwarding an unrelated file.

Search covers the shared library and the current conversation only. Group
attachments never appear in DM searches, and one group's attachments cannot be
retrieved from another group. Deleted messages are excluded. Results contain
IDs, source, type, description and scores; storage paths are not exposed.

To send a result, the agent emits `send_audio`, `send_image` or `send_video` with
`{"media_id": 123, "media_source": "library|conversation"}`. To forward an
attachment explicitly selected or quoted by the user, it can instead pass
`{"message_id": 123}`. IDs refer to database message IDs shown in context. The
application checks scope and type again before downloading or sending. Stickers
use `send_image` and retain sticker delivery. Legacy `media_id`-only actions still
refer to the shared library.

Startup migrations add descriptions and embeddings to `content.sup_media`.
Asset initialization copies descriptions from `assets/metadata.yaml`, generating
embeddings only when descriptions changed or the vector is missing. New incoming
audio transcripts are indexed in both the media and message records. Semantic
search also backfills up to 20 older, already-transcribed audio attachments from
the current conversation per request in one embedding batch; tool output reports
whether more remain. Untranscribed recordings cannot be searched by spoken words.
No transcription or description is invented for missing content.

Generation uses configured OpenRouter models, WhatsApp transfers use WAHA, and
archived media is stored in MinIO. Commands require an authorized conversation
and the corresponding permissions.

## Images and references

Use `!image <prompt>` to create an image. Attach a photo or reply to one to edit
it: `!image make the sky look like sunset`. Mention a person to add their saved
profile photo as an identity reference; `@me` selects your own photo.

Gork separates the image being edited from identity references. Quoting a text
message does not automatically add its author's face or old words to the prompt.
Provider capabilities and reference limits can restrict how many images fit in
one request. Missing references or provider failures produce a failure message.

| Command | Use |
| --- | --- |
| `!describe` | Describe an attached or quoted image |
| `!picture @user` | Send a mentioned user's saved profile photo |
| `!deactivate @user` | Make a profile photo grayscale with a “Deactivated account” footer |
| `!deactivate` replying to a photo | Apply that treatment to the photo |
| `!deactivate` alone | Use a random photo; mentions of Gork are ignored |
| `!philo :quote socrates` | Render a quote on a philosopher image |

Profile-based commands need a saved photo. Privacy settings or a missing local
record can make it unavailable even when the person is known to WhatsApp.

## Stickers

Use `!sticker` with attached or quoted media. Quoted text can become a quote
card using its sender's profile image.

```text
!sticker top caption | bottom caption
!sticker :no-background t
!sticker :fill t :direction top
!sticker :effect rotation :speed 2
!sticker :cut 1:00-1:05
!sticker :tweet https://x.com/user/status/12345
```

Parameters also accept `:name=value`. `:direction` selects the preserved crop
area; fill defaults to the center. Effects can animate static photos. `:cut`
selects a video interval; `:speed` has effect-specific behavior for rotation and
explosions. `:dead` creates a tombstone-style quote.

Tweet cards include author, avatar, text, and the first media preview when
available. Text-only posts work, and long text is shortened to fit. Use `!help`
for all filters, effects, ranges, and examples.

Background removal uses local `rembg`. Animated stickers and video processing
need FFmpeg. These are image/video dependencies, independent of speech services.

## Generate video

```text
!video a paper boat sailing across a desk :duration 5 :quality 720
!video animate this scene :duration 10 :audio t
```

Attach or quote media and mention people to provide references. Default duration
is 5 seconds, with a 10-second maximum. Quality defaults to the lowest supported
by the selected model; audio is off unless requested. Capabilities differ by
model, so not every combination of quality, duration, audio, and references works.

Gork submits a background job, polls it, downloads the result, and sends the
finished video. It reports unsupported options or provider failures in chat.
References may be uploaded to the temporary file service when the provider needs
a public URL.

## Downloads and archives

`!twitter <url>` sends a video or the first photo from an X/Twitter post.
`!youtube <url>` sends a public YouTube video or Short as MP4, up to 16 MiB.
Use `!sticker <url>` or reply to a message with a YouTube link using `!sticker`
to create an animated sticker from a video within the same size limit. You
can select a clip with `:cut 0:02-0:05`.
Both commands accept `youtube.com/watch?v=…`, `youtube.com/shorts/…`, and
`youtu.be/…` links.
`!instagram <reel-url>` downloads a reel; some sources require the optional
`INSTAGRAM_COOKIES_FILE`. In Docker, mount that file and configure its path as
seen inside the application container.

`!gallery` finds saved images by terms/dates. The panel's Data views add
contact/group/date filters, previews, authenticated downloads, and semantic
search. These views show Gork's saved records, not a live mirror of all WhatsApp
media.

Archived MinIO copies can support media recovery after WAHA URLs expire. A
database reference alone cannot recover an old file that was never archived.
See [data browsing](admin-panel.md) and [backups](development.md#state-and-recovery).
