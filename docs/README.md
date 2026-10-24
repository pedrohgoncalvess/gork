# Gork documentation

Start with the [README](../README.md) to install Gork and pair WhatsApp. These
guides explain feature behavior, configuration, examples, and troubleshooting.
Some operational guides are in Portuguese, matching the panel and bot messages.

| Guide | What you will learn |
| --- | --- |
| [Conversations](conversations.md) | DMs, group mentions, automatic replies, summaries, and search |
| [Media](media.md) | Images, video, stickers, downloads, and saved media |
| [Voice](audio-generation.md) | Configure OpenRouter TTS/STT and understand the audio path |
| [Reminders, favorites, and usage](reminders-and-usage.md) | Schedule messages, bookmark replies, and inspect consumption |
| [Observations](observations.md) | Scoped long-term notes and retrieval |
| [Temporary group bans](group-ban.md) | Polls, quorum, and moderation controls |
| [WAHA](waha.md) | Pairing, webhooks, sessions, and delivery troubleshooting |
| [Admin panel](admin-panel.md) | Access lists, synchronization, agent settings, and data search |
| [MCP servers](mcp.md) | Remote tools, authentication, scopes, and call history |
| [Development and deployment](development.md) | Docker layout, tests, rebuilds, and backups |
| [Agent packages](agents.md) | Locate or extend each agent's code, prompt, parser, and schema |
| [Gork knowledge base](knowledge/README.md) | On-demand tool for project history, capabilities, architecture, security, and setup |
| [Data encryption](encryption.md) | Encryption coverage, keys, search behavior, and deployment prerequisites |

Send `!help` inside WhatsApp for the command catalog. Its source is
`api/routes/webhook/waha/handles/core.py`; keep it and the guides in sync when
adding or changing commands.
