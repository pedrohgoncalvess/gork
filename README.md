# Gork

An open source WhatsApp bot for conversations, media creation, and group tools. Run it on your own infrastructure and choose the AI models that power it.

Built with Python, FastAPI, WAHA (GOWS), OpenRouter, PostgreSQL with pgvector, MinIO, and Redis.

[Features](#features) · [Getting started](#getting-started) · [Development](#development) · [Documentation](#documentation) · [Contributing](#contributing)

## Features

- **Conversations with context:** chat in DMs or groups, follow replies, summarize messages, and remember useful observations across conversations.
- **Images and video:** generate and edit images, describe photos, and create short videos with reference images.
- **Voice:** transcribe audio and reply with generated speech.
- **Stickers and memes:** turn photos, videos, quoted messages, and X/Twitter posts into stickers. Add captions, effects, background removal, or a “Deactivated account” photo treatment.
- **Media and organization:** download X/Twitter media and Instagram reels, browse saved images, favorite messages, and schedule reminders.
- **Group tools:** optional automatic replies, temporary bans through polls, access lists, and command permissions.
- **Admin panel:** connect WhatsApp, import contacts and history, manage users and groups, configure agents and models, and inspect usage.
- **MCP integrations:** connect remote tool servers and make their tools available to the conversation agents.

## Getting started

### Requirements

- Git, Docker with Docker Compose, and [uv](https://docs.astral.sh/uv/).
- Python 3.13 or newer; uv can provision it when needed.
- An OpenRouter API key and a WhatsApp account to connect.

### 1. Clone and configure

```sh
git clone https://github.com/pedrohgoncalvess/gork.git
cd gork
uv sync --frozen
uv run python -m scripts.setup
```

The setup script creates `.env` from [.env.example](.env.example), generates missing secrets, and prints the initial admin password. Running it again preserves existing credentials.

Set `OPENROUTER_KEY` in `.env`. The default database and storage settings match the bundled local stack. Add optional service credentials only for the integrations you use, such as `FIRECRAWL_KEY` for page extraction.

### 2. Start the stack

Create the shared Docker network once; skip this command if it already exists:

```sh
docker network create dokploy-network
```

Start the infrastructure, then the application:

```sh
docker compose -f docker-compose.dev.yaml up -d --build --wait postgres s3-minio redis waha
docker compose -f docker-compose.dev.yaml up -d --build webhook-fastapi
```

This runs Gork, WAHA, PostgreSQL, MinIO, and Redis. Database migrations and initial agent configuration run automatically at application startup.

### 3. Connect WhatsApp

Open [localhost:9001/admin](http://localhost:9001/admin) and sign in with the generated `ADMIN_PASSWORD` from `.env`.

In **Connection → WhatsApp**, scan the QR code with WhatsApp's **Linked devices** feature and wait for `WORKING`. Gork configures the session and webhook automatically.

Authorize users and groups through the panel's access lists. For an isolated trial, configure a test number in the panel; test mode accepts only that contact in DMs and ignores groups. Review the configured agents and models to match your OpenRouter access.

See the [admin panel guide](docs/admin-panel.md) and [WAHA guide](docs/waha.md) for details. Some guides and panel labels are currently in Portuguese.

### 4. Try it

Send `!help` in an authorized chat for the full command list. In groups, mention Gork to start a conversation.

| Command | What it does |
| --- | --- |
| `!status` / `!model` | Check availability and the current model |
| `!resume` | Summarize recent messages |
| `!image <prompt>` / `!video <prompt>` | Generate images or short videos |
| `!sticker` | Create a sticker from attached or quoted media |
| `!sticker :tweet <url>` | Turn an X/Twitter post into a sticker |
| `!deactivate @user` | Create a “Deactivated account” image from a saved profile photo |
| `!transcribe` | Transcribe a quoted audio message |
| `!remember <request>` | Schedule a reminder using natural language |
| `!gallery` / `!favorite` | Browse saved images or favorite a message |
| `!usage` | View token usage reports |

### Logs and shutdown

```sh
docker compose -f docker-compose.dev.yaml logs -f webhook-fastapi
docker compose -f docker-compose.dev.yaml down
```

Named volumes preserve the database, media, and WhatsApp session between restarts.

### Deployment

[compose.yaml](compose.yaml) runs Gork, WAHA, and Redis with an external PostgreSQL database and MinIO storage. Set their connection details and your own credentials in `.env`, create `dokploy-network` if needed, then run:

```sh
docker compose -f compose.yaml up -d --build
```

Use HTTPS for remote access to the admin panel. The bundled development credentials are intended for local use.

## Development

Start with the setup above. The development Compose file mounts the application source into the container, so you can edit locally and restart the app to load Python changes:

```sh
docker compose -f docker-compose.dev.yaml restart webhook-fastapi
```

After changing dependencies, update the lockfile with uv and rebuild:

```sh
uv sync
docker compose -f docker-compose.dev.yaml up -d --build webhook-fastapi
```

### Tests

Run the suite inside the application container so the database and other service hostnames resolve:

```sh
docker compose -f docker-compose.dev.yaml exec webhook-fastapi python -m unittest discover -s tests
```

Tests are included in the image; rebuild after editing tests. For local Python tooling, `uv sync --frozen` prepares `.venv`. Running the API or tests on the host requires FFmpeg for media operations and reachable service addresses:

| Setting | Docker application | Host process |
| --- | --- | --- |
| `PG_HOST` | `gork_postgres` | `localhost` |
| `PG_PORT` | `5432` | `5435` |
| `MINIO_ENDPOINT` | `s3-minio:19000` | `localhost:19000` |
| `REDIS_URL` | `redis://redis:6379/0` | `redis://localhost:6379/0` |
| `WAHA_BASE_URL` | `http://waha:3000` | `http://localhost:3002` |

Keep the Docker application's `.env` settings intact when configuring a host process. If running the API on the host, also set `WAHA_WEBHOOK_URL` to an address reachable from the WAHA container.

### Project layout

```text
api/          Webhooks, command handlers, and admin panel
agents/       Agent configuration, prompts, schemas, and execution
external/     WAHA, OpenRouter, and other service clients
database/     Models, repositories, and migrations
services/     Conversation context, media storage, access rules, and setup
scheduler/    Scheduled jobs
assets/       Fonts, emoji, and bundled media
tests/        Automated tests
docs/         Feature and configuration guides
```

For new commands, add a handler under `api/routes/webhook/waha/handles/`, register dispatch in `processors/common.py` under the same `waha/` directory, and update the `COMMANDS` catalog in `handles/core.py`. Include tests for the behavior you add.

## Documentation

- [WhatsApp connection and WAHA configuration](docs/waha.md)
- [Admin panel, access lists, and synchronization](docs/admin-panel.md)
- [Remote MCP servers](docs/mcp.md)
- [Voice generation](docs/audio-generation.md)
- [Conversation observations](docs/observations.md)
- [Temporary group bans](docs/group-ban.md)

## Contributing

Bug reports, documentation improvements, and pull requests are welcome. Open an [issue](https://github.com/pedrohgoncalvess/gork/issues) with reproduction steps and relevant logs, or describe the feature you would like to work on. Remove credentials and personal conversation data from anything you share.

Keep pull requests focused, explain the resulting behavior, and include relevant test results. Changes to configuration or commands should update the corresponding documentation.

## License

[Apache License 2.0](LICENSE).
