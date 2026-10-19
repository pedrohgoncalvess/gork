# 🤖 Gork - WhatsApp Bot

> Intelligent WhatsApp bot powered by LLMs, WAHA (GOWS), and modern Python stack.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Detailed Setup](#detailed-setup)
- [Configuration](#configuration)
- [Usage](#usage)
- [Development](#development)
- [Troubleshooting](#troubleshooting)
- [Architecture](#architecture)
- [Contributing](#contributing)

---

## 🎯 Overview

**Gork** is a sophisticated WhatsApp bot that uses Large Language Models (LLMs) to provide intelligent responses. It's built with Python 3.13, FastAPI, and integrates with WAHA (GOWS) for WhatsApp connectivity.

### Key Components

- **Core Application**: FastAPI server handling webhook events
- **Database**: PostgreSQL with pgvector extension for embeddings
- **Storage**: MinIO S3-compatible object storage
- **WhatsApp Integration**: WAHA (GOWS) for message handling
- **LLM Integration**: OpenRouter, Firecrawl, Brave Search, and more

---

## ✨ Features

- **🧠 Intelligent Conversations**: LLM-powered responses with context awareness
- **📡 Webhook-based**: Real-time message processing via WAHA (GOWS)
- **🔌 Multi-service Integration**: Search, translation, transcription, image generation
- **🎨 Sticker Creation**: Convert images to stickers with effects
- **🐦 Tweet Stickers**: `!sticker :tweet https://x.com/user/status/12345` creates a 512 × 512 tweet card with author, avatar, original text and the first photo (or video preview). Also works with text-only tweets and links in quoted messages. Long text is shortened with an ellipsis to keep it readable.
- **📹 Media Handling**: Support for images, videos, audio transcription
- **📝 Post Management**: Create, read, and list blog posts
- **🖼️ Gallery & Projects**: Dynamic content display
- **⏰ Reminders**: Scheduled notifications using APScheduler
- **⭐ Favorites**: Save and manage favorite messages
- **📊 Consumption Reports**: Track token usage by user/group

---

## 🔧 Prerequisites

### Required

- **Python 3.13+**
  ```bash
  python --version  # Should be 3.13 or higher
  ```

- **Docker & Docker Compose**
  ```bash
  docker --version
  docker compose version
  ```

- **Make Utility**
  ```bash
  make --version
  ```

### Optional (for local development)

- **UV** (Python package manager) - will be installed automatically if missing
- **Git** - for cloning the repository

---

## 🚀 Quick Start

### 1. Clone Repository

```bash
git clone https://github.com/pedrohgoncalvess/gork.git
cd gork
```

### 2. Configure Environment Variables

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your configuration
nano .env  # or use your preferred editor
```

### 3. Setup Environment

```bash
# This will install UV, create virtual environment, and install dependencies
make setup
```

### 4. Start Services

```bash
# Start all services (PostgreSQL, MinIO, Gork app)
docker compose -f docker-compose.dev.yaml up -d

# Start WAHA (GOWS)
make waha-start
```

### 5. Configure WAHA (GOWS)

See [WAHA migration](docs/waha-migration.md) section below.

---

## 📚 Detailed Setup

### Step 1: Environment Configuration

The `.env` file contains all configuration for the application. Here's a breakdown:

#### Application Settings

```bash
# Maintenance mode (optional)
MAINTENANCE=false                  # Set to true to block bot access
MAINTENANCE_NUMBER=5511999999999  # Phone number that bypasses maintenance
ENV=dev                            # Environment (dev/prod)
```

#### Database Configuration

```bash
# PostgreSQL settings
PG_HOST=gork_postgres              # Hostname (Docker service name)
PG_PORT=5432                       # Port
PG_USER=admin                       # Username
PG_PASSWORD=admin                   # Password
PG_NAME=postgres                    # Database name
```

#### MinIO S3 Configuration

```bash
# Object storage for files
MINIO_ENDPOINT=s3-minio:19000     # Host:port
MINIO_ACCESS_KEY=minioadmin         # Access key
MINIO_SECRET_KEY=minioadmin         # Secret key
MINIO_USE_SSL=false                  # SSL (usually false for local dev)
```

#### WAHA (GOWS) Configuration

```dotenv
WAHA_BASE_URL=http://waha:3000
WAHA_API_KEY=your-long-random-api-key
WAHA_SESSION=default
WAHA_WEBHOOK_TOKEN=your-separate-webhook-secret
WHATSAPP_INSTANCE_NUMBER=your-existing-bot-number
WAHA_PORT=3002
```

See [WAHA migration](docs/waha-migration.md) for pairing and existing-data compatibility.

#### LLM & Service APIs

```bash
# OpenRouter (for LLM models)
OPENROUTER_KEY=your_openrouter_key

# Firecrawl (web scraping)
FIRECRAWL_KEY=your_firecrawl_key

# Ninja API (additional services)
NINJA_KEY=your_ninja_key

# Brave Search (web search)
BRAVE_KEY=your_brave_search_key
BRAVE_API=https://api.search.brave.com

# GoFile (file sharing, optional)
GOFILE_KEY=your_gofile_key
```

### Step 2: Virtual Environment Setup

The `make setup` command automates the entire setup process:

```bash
make setup
```

This command does the following:

1. **Checks UV installation** - Installs UV if not present
2. **Verifies Python version** - Ensures Python 3.13+ is available
3. **Creates virtual environment** - Uses UV to create a venv
4. **Installs dependencies** - Syncs dependencies from `pyproject.toml`

#### Custom Python Path

If you want to use a specific Python installation:

```bash
# Linux/macOS
make setup PYTHON_PATH="/usr/local/bin/python3.13"

# Windows
make setup PYTHON_PATH="C:\\Python313\\python.exe"
```

### Step 3: Database Setup

The PostgreSQL database is automatically set up via Docker Compose:

```yaml
# From docker-compose.yaml
postgres:
  image: pgvector/pgvector:pg16
  environment:
    POSTGRES_USER: admin
    POSTGRES_PASSWORD: admin
    POSTGRES_DB: postgres
  ports:
    - "5435:5432"  # Maps to localhost:5435
```

**Accessing database locally:**

```bash
# Connect via psql
psql -h localhost -p 5435 -U admin -d postgres

# Connect via Python
python -c "import psycopg2; conn = psycopg2.connect(host='localhost', port=5435, user='admin', password='admin', dbname='postgres'); print('Connected!')"
```

### Step 4: Storage Setup (MinIO)

MinIO is an S3-compatible object storage used for storing files:

```yaml
# From docker-compose.yaml
s3-minio:
  image: minio/minio
  ports:
    - "19000:19000"  # API port
    - "19001:19001"  # Console port
  environment:
    MINIO_ROOT_USER: minioadmin
    MINIO_ROOT_PASSWORD: minioadmin
  volumes:
    - minio_data:/data
```

**Access MinIO Console:**

1. Open browser: `http://localhost:19001`
2. Login with: `minioadmin` / `minioadmin`
3. Create buckets as needed

### Step 5: WAHA / GOWS Setup

Both compose files include WAHA using the same pinned GOWS image as Orbia.
Run the session helper inside the Gork service to configure the authenticated
webhook, start the session and obtain a QR code. Follow the complete
[WAHA migration and pairing guide](docs/waha-migration.md).

### Step 6: Start Gork Application

Now everything is ready to start the bot:

```bash
# Using Docker Compose (recommended)
docker compose -f docker-compose.dev.yaml up -d

# The bot will be available at http://localhost:9001
# Check logs: docker compose logs -f webhook-fastapi
```

---

## ⚙️ Configuration

### Using Custom Environment Files

You can create multiple environment files for different scenarios:

```bash
# Development
cp .env.example .env.dev
# Edit .env.dev
docker compose -f docker-compose.dev.yaml --env-file .env.dev up -d

# Production
cp .env.example .env.prod
# Edit .env.prod
docker compose -f docker-compose.dev.yaml --env-file .env.prod up -d
```

### Docker Compose Services

The `docker-compose.yaml` defines three main services:

#### 1. PostgreSQL (`gork_postgres`)

- **Image**: `pgvector/pgvector:pg16`
- **Ports**: `5435:5432` (host:container)
- **Purpose**: Stores conversation history, embeddings, and user data
- **Volume**: `postgres_data` (persistent storage)
- **Healthcheck**: Monitors database readiness

#### 2. Webhook FastAPI (`webhook_fastapi`)

- **Build**: From `Dockerfile` (Python 3.13)
- **Ports**: `9001:9001`
- **Purpose**: Main Gork application
- **Volumes**: Mounts source code, `.env` file, and various directories
- **Restart**: `unless-stopped`

#### 3. MinIO S3 (`s3-minio`)

- **Image**: `minio/minio`
- **Ports**: `19000:19000` (API), `19001:19001` (Console)
- **Purpose**: File storage
- **Volume**: `minio_data` (persistent storage)
- **Restart**: `unless-stopped`

### Network Configuration

All services communicate via `dokploy-network` external network:

```yaml
networks:
  dokploy-network:
    external: true
```

**Create network if it doesn't exist:**

```bash
docker network create dokploy-network
```

---

## 🎮 Usage

### Available Make Commands

```bash
# Setup Commands
make setup              # Install UV, create venv, install dependencies
make clean               # Remove virtual environment
make check-uv           # Check if UV is installed
make install-uv         # Install UV manually
make check-python        # Check Python version
make create-venv         # Create virtual environment
make install-deps        # Install dependencies

# Run Commands
make run                 # Run with Python directly (local dev)
docker compose -f docker-compose.dev.yaml up -d   # Run with Docker (recommended)

# WAHA Commands
make waha-start          # Build/start the GOWS container
make waha-stop           # Stop WAHA, preserving its volumes
make waha-logs           # View WAHA logs
make waha-configure      # Configure/start the session (Gork must be running)
```

### Starting All Services

```bash
# 1. Start Docker services (PostgreSQL, MinIO, Gork)
docker compose -f docker-compose.dev.yaml up -d

# 2. Start WAHA (GOWS)
make waha-start

# 3. Check logs
docker compose -f docker-compose.dev.yaml logs -f webhook-fastapi

# 4. Verify WAHA (GOWS)
curl http://localhost:3002

# 5. Verify Gork API
curl http://localhost:9001
```

### Testing the Bot

1. **Send a message to your WhatsApp number**
2. **Check logs**: `docker compose logs -f webhook-fastapi`
3. **Verify webhook**: Use `scripts.waha_session status` and the [pairing guide](docs/waha-migration.md).
4. **Test commands**:
   - `!help` - Shows available commands
   - `!model` - Shows current model
   - `!search <query>` - Web search

### Stopping All Services

```bash
# 1. Stop Gork and Docker services
docker compose -f docker-compose.dev.yaml down

# 2. Stop WAHA (GOWS)
make waha-stop
```

---

## 🛠️ Development

### Running Locally (without Docker)

```bash
# Setup environment
make setup

# Start services (PostgreSQL and MinIO)
docker compose -f docker-compose.dev.yaml up -d postgres s3-minio

# Run Gork locally
make run
# Or: source .venv/bin/activate && uvicorn main:app --host 0.0.0.0 --port 9001
```

### Project Structure

```
gork/
├── api/                    # API routes and handlers
│   └── routes/
│       └── webhook/
│           ├── waha/    # WAHA (GOWS) webhook handlers
│           └── ...
├── agents/                 # AI agents configuration
├── database/               # Database models and operations
├── external/               # External service integrations
│   ├── waha/          # WAHA (GOWS) client
│   ├── firecrawl.py        # Web scraping
│   └── ...
├── services/               # Business logic services
├── scheduler/              # APScheduler setup
├── s3/                    # MinIO S3 operations
├── utils/                  # Utility functions
├── main.py                # Application entry point
├── docker-compose.yaml      # Docker services definition
├── Dockerfile             # Container build config
├── pyproject.toml         # Python dependencies
├── uv.lock                # Locked dependency versions
├── .env.example            # Environment template
└── makefile               # Build and run commands
```

### Adding New Commands

To add a new command to Gork:

1. **Create handler function** in `api/routes/webhook/waha/handles.py`

```python
# Example: New command handler
async def handle_new_command(
    remote_id: str,
    conversation: str,
    message_id: str
):
    """
    Handler for new command.
    
    Args:
        remote_id: ID of the recipient (phone or group)
        conversation: Full message text
        message_id: ID of message for reply
    """
    await send_message(remote_id, "This is a new command!", message_id)
```

2. **Add command to list** in `handles.py`:

```python
COMMANDS = [
    # ... existing commands
    ("!newcommand", "Description of new command", "category", []),
]
```

3. **Register handler call** in `processors.py`:

```python
async def process_explicit_commands(...):
    # ... existing checks
    if "!newcommand" in lw_conversation:
        await handle_new_command(remote_id, conversation, message_id)
        return
    # ... rest of function
```

4. **Update help** (if applicable):

The `!help` command automatically uses the `COMMANDS` list, so just adding it there is enough.

### Debugging

**Enable verbose logging:**

```bash
# In .env
ENV=debug
```

**Check logs:**

```bash
# Gork logs
docker compose -f docker-compose.dev.yaml logs -f webhook-fastapi

# PostgreSQL logs
docker compose -f docker-compose.dev.yaml logs -f gork_postgres

# All logs
docker compose -f docker-compose.dev.yaml logs
```

---

## 🔍 Troubleshooting

### WAHA connectivity, QR code or webhook errors

Use `make waha-logs` and the `scripts.waha_session status` command described in
[the migration guide](docs/waha-migration.md). The session must be `WORKING`,
`WAHA_API_KEY` must match the container, and `X-Webhook-Token` must match
`WAHA_WEBHOOK_TOKEN`. Subscribe only to `message.any`. Keep the existing bot
number and whitelist entries. The API listens on localhost port 3002 by default.

### Database Connection Errors

**Check if PostgreSQL is running:**

```bash
docker ps | grep gork_postgres
```

**Test connection:**

```bash
psql -h localhost -p 5435 -U admin -d postgres
```

**Common solutions:**

```bash
# Reset database volume (WARNING: deletes all data)
docker compose -f docker-compose.dev.yaml down -v
docker compose -f docker-compose.dev.yaml up -d

# Check port conflicts
lsof -i :5435  # macOS/Linux
netstat -ano | findstr :5435  # Windows
```

### Dependencies Installation Issues

**If `make setup` fails:**

```bash
# 1. Check Python version
python --version  # Should be 3.13+

# 2. Clear virtual environment
make clean

# 3. Install UV manually
# Linux/macOS
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
curl -Lo uv-installer.exe https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.exe
./uv-installer.exe /quiet

# 4. Re-run setup
make setup
```

### UV Installation Issues on Windows

**If UV installation fails:**

```bash
# 1. Manually download installer
# Download from: https://github.com/astral-sh/uv/releases/latest

# 2. Run installer (PowerShell as Administrator)
.\uv-installer.exe /quiet

# 3. Verify installation
uv --version

# 4. Add to PATH manually
# Add C:\Users\<Username>\.local\bin to PATH

# 5. Use custom path in make
make setup PYTHON_PATH="C:\\Python313\\python.exe"
```

### MinIO Connection Errors

**Check if MinIO is running:**

```bash
docker ps | grep s3-minio
```

**Access MinIO console:**

```bash
# Open browser: http://localhost:19001
# Login: minioadmin / minioadmin
```

**Verify configuration in .env:**

```bash
MINIO_ENDPOINT=s3-minio:19000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_USE_SSL=false
```

**Test connection:**

```bash
# From within container
docker compose -f docker-compose.dev.yaml exec s3-minio mc alias set local http://localhost:19000 minioadmin minioadmin
docker compose -f docker-compose.dev.yaml exec s3-minio mc ls local
```

### Port Conflicts

**Check which ports are in use:**

```bash
# macOS/Linux
lsof -i :5435  # PostgreSQL
lsof -i :9001  # Gork API
lsof -i :3002  # WAHA (GOWS)
lsof -i :19000  # MinIO API
lsof -i :19001  # MinIO Console

# Windows
netstat -ano | findstr :5435
netstat -ano | findstr :9001
netstat -ano | findstr :3002
netstat -ano | findstr :19000
netstat -ano | findstr :19001
```

**Change ports if needed:**

Edit `docker-compose.yaml`:

```yaml
services:
  postgres:
    ports:
      - "5436:5432"  # Changed from 5435

  webhook-fastapi:
    ports:
      - "9002:9001"  # Changed from 9001

  s3-minio:
    ports:
      - "19002:19000"  # Changed from 19000
      - "19002:19001"  # Changed from 19001
```

**Remember to update `.env` with new ports!**

---

## 🏗️ Architecture

### System Overview

```
┌──────────────────────────────────────────────────┐
│                    User Messages                     │
│                      ↓                             │
│              WAHA / GOWS (3000)                 │
│                      ↓                             │
│              Webhook Endpoint                    │
│                      ↓                             │
│            ┌────────────────────┐               │
│            │  Gork App (9001) │               │
│            │  - FastAPI       │               │
│            │  - LLMs          │               │
│            │  - Scheduler     │               │
│            └────────────────────┘               │
│           ↓           ↓           ↓              │
│      PostgreSQL    MinIO    External APIs         │
│      (5435)       (19000)   (OpenRouter,     │
│                                Brave, etc.)      │
└──────────────────────────────────────────────────┘
```

### Data Flow

1. **User sends WhatsApp message** → WAHA (GOWS) receives it
2. **WAHA (GOWS) sends webhook** → Gork FastAPI server
3. **Gork processes message** → Classifies intent, calls appropriate service
4. **LLM generates response** → OpenRouter or configured LLM
5. **Gork sends response** → WAHA (GOWS) → WhatsApp

### Key Components

- **FastAPI Server**: Handles incoming webhooks and exposes API endpoints
- **Webhook Handler**: Processes WAHA (GOWS) events (messages, status, etc.)
- **Intent Classifier**: Determines user intent (search, image, help, etc.)
- **LLM Integration**: Communicates with OpenRouter, Firecrawl, etc.
- **Database Layer**: Stores conversation history, user data, embeddings
- **Scheduler**: Manages reminders and scheduled tasks
- **S3 Storage**: Handles file uploads and storage

---

## 📝 Contributing

Contributions are welcome! Here's how to get started:

### Development Workflow

```bash
# 1. Fork and clone
git clone https://github.com/your-username/gork.git
cd gork

# 2. Create a feature branch
git checkout -b feature/your-feature-name

# 3. Make your changes
# Edit code, add features, fix bugs

# 4. Test your changes
make setup
docker compose -f docker-compose.dev.yaml up -d
# Test thoroughly

# 5. Commit changes
git add .
git commit -m "feat: Add your feature"

# 6. Push to your fork
git push origin feature/your-feature-name

# 7. Create Pull Request
# Go to GitHub and create a PR to pedrohgoncalvess/gork:main
```

### Code Style

- Follow PEP 8 (Python style guide)
- Use type hints for all functions
- Write docstrings for all modules and functions
- Keep functions small and focused
- Use descriptive variable names

### Adding New Features

1. **Create handler function** in `api/routes/webhook/waha/handles.py`
2. **Add command to list** in `COMMANDS` array
3. **Register processor call** in `processors.py` → `process_explicit_commands()`
4. **Update documentation** in this README
5. **Test thoroughly** before submitting PR

Example:

```python
# In handles.py
async def handle_new_command(
    remote_id: str,
    message_id: str,
    # ... other params
):
    await send_message(remote_id, "This is a new command!", message_id)

# In handles.py COMMANDS
COMMANDS = [
    # ... existing commands
    ("!newcommand", "Description of new command", "category", []),
]

# In processors.py
async def process_explicit_commands(...):
    # ... existing checks
    if "!newcommand" in lw_conversation:
        await handle_new_command(remote_id, message_id, ...)
        return
    # ... rest of function
```

---

## 📄 License

This project is licensed under the [Apache License](LICENSE).

---

## 🙏 Acknowledgments

- [WAHA](https://waha.devlike.pro/docs/) - WhatsApp API integration
- [OpenRouter](https://openrouter.ai/) - LLM API provider
- [FastAPI](https://fastapi.tiangolo.com/) - Web framework
- [UV](https://github.com/astral-sh/uv) - Fast Python package manager
- [pgvector](https://github.com/pgvector/pgvector) - Vector similarity for PostgreSQL

---

## 📞 Support

For issues, questions, or suggestions:

- Create an [Issue](https://github.com/pedrohgoncalvess/gork/issues)
- Check [Discussions](https://github.com/pedrohgoncalvess/gork/discussions)
- Review existing issues and PRs

---

## 🗺 Roadmap

- [ ] Multi-language support
- [ ] Voice messages (TTS)
- [ ] Image upload and processing
- [ ] Group analytics dashboard
- [ ] Rate limiting and spam protection
- [ ] Web admin interface

---

**Built with ❤️ by Pedro Gonçalves**
