# Images, video, stickers, and saved media

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
