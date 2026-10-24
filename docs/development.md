# Development and deployment

Run commands from the repository root. Prepare dependencies with
`uv sync --frozen`, run `uv run python -m scripts.setup`, and configure the
provider credentials in `.env` before starting services.

## Docker layout

| File | Purpose |
| --- | --- |
| `compose.yaml` | Deployment with external PostgreSQL and MinIO |
| `docker/compose.dev.yaml` | Local/test stack including database and storage |
| `docker/Dockerfile` | Application image used by both stacks |
| `docker/waha/Dockerfile` | Pinned WAHA image and volume permissions |

The nested Compose file resolves contexts and mounts relative to `docker/`.
Its project name stays `gork`, preserving the default `gork_*` volume names
after the move. If an installation used `-p` or `COMPOSE_PROJECT_NAME`, retain
that value to reuse its volumes.

Use `--env-file .env` with the development file so interpolation reads the root
credentials. The app separately receives the root `.env` as a read-only mount;
Compose interpolation and the application environment are different layers.

## Local workflow

Create `dokploy-network` once if it does not exist, then start the stack:

```sh
docker network create dokploy-network
docker compose --env-file .env -f docker/compose.dev.yaml up -d --build --wait postgres s3-minio redis waha
docker compose --env-file .env -f docker/compose.dev.yaml up -d --build webhook-fastapi
```

Connect WhatsApp in [the panel](http://localhost:9001/admin). Use a test number
for isolated DM development; disable test mode to exercise group features.
The source directories are mounted into the development container. Workers do
not reload Python automatically, so restart after edits:

```sh
docker compose --env-file .env -f docker/compose.dev.yaml restart webhook-fastapi
docker compose --env-file .env -f docker/compose.dev.yaml logs -f webhook-fastapi
```

Tests, scripts, and bundled assets are copied into the image, not mounted.
Rebuild when changing them, dependencies, or Docker configuration:

```sh
uv sync
docker compose --env-file .env -f docker/compose.dev.yaml up -d --build webhook-fastapi
docker compose --env-file .env -f docker/compose.dev.yaml exec webhook-fastapi python -m unittest discover -s tests
```

For host tests, use `uv run python -m unittest discover -s tests` and the
[host service addresses](../README.md#tests). Use process environment overrides
instead of replacing Docker hostnames in the app's mounted `.env`. Media tests
may need FFmpeg; provider calls should be mocked in unit tests.

## Deployment

Set `PG_*`, `MINIO_*`, and provider credentials for your external services.
PostgreSQL needs pgvector and permission to create the required schemas and
extensions. Start the root Compose file:

```sh
docker compose -f compose.yaml up -d --build
docker compose -f compose.yaml logs -f api
```

The deployment service is `api`; development uses `webhook-fastapi`. Both expose
9001 and use `http://gork-api:9001/webhook/waha` internally, through the
network alias shared by both stacks. Run one stack per bot:
ports, container names, and the WhatsApp session overlap. Put HTTPS in front of
remote admin access and replace the bundled local infrastructure credentials.

## State and recovery

Migrations run before agent/asset initialization and scheduled jobs. Inspect
startup logs first when the panel cannot connect: a database failure can prevent
the app from reaching WhatsApp setup.

Startup uses a PostgreSQL session advisory lock before creating `yoyo_lock` and
running migrations, so multiple workers/containers can bootstrap a fresh database.
Use a direct PostgreSQL connection (or session pooling) for the startup `PG_*`
connection; transaction pooling cannot preserve session locks. The database role
must have CREATE permission on the current schema and access to existing Yoyo
tables. Permission errors are reported directly instead of being hidden behind
`relation "yoyo_lock" does not exist`.

Back up PostgreSQL, MinIO objects, WAHA sessions/media, and `.env` together.
The database stores message references, access rules, reminders, agent overrides,
and encrypted MCP settings. Preserve `DATA_ENCRYPTION_KEY` for encrypted fields
and attachments, and `MCP_ENCRYPTION_KEY` for MCP connection settings. Keep a
separate protected copy of these keys; a new key cannot decrypt existing data.
See [encryption prerequisites and limits](encryption.md) before deployment.

`docker compose ... down` preserves named volumes; adding `-v` deletes them and
is not routine troubleshooting. A WAHA cache does not replace MinIO archives,
and a database backup does not contain attachment binaries.
