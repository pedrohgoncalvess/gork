# Gork Setup Guide

## Prerequisites

- **Python 3.13+**
- **Docker** and **Docker Compose**
- **Make** utility

## Installation

### 1. Configure Environment Variables

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env and fill in the missing parameters
```

Open the `.env` file and complete all required parameters.

### 2. Install Dependencies and Setup Environment

```bash
make setup
```

This will automatically install UV, create a virtual environment, and install all dependencies.

**Optional - Using a Custom Python Path:**

```bash
# Windows
make setup PYTHON_PATH="C:\Python313\python.exe"

# Linux/macOS
make setup PYTHON_PATH="/usr/local/bin/python3.13"
```

## Running the Application

```bash
make run
```

## Evolution API Setup

### 1. Start Evolution API

```bash
make evolution-start
```

The API will be available at `http://localhost:8080`

### 2. Create Instance

1. Open your browser and go to `http://localhost:8080`
2. Click **"Create Instance"**
3. Set the instance name to: **`Gork`**
4. Click **"Create"** or **"Save"**

### 3. Configure Webhook

1. In the instance settings, go to the **Events** tab
2. Navigate to **Webhook** section
3. Enable the webhook toggle
4. Set the webhook URL to: `http://webhook_fastapi:9001/webhook/evolution`
5. Save the configuration

### 4. Connect Your Phone

1. A QR code will appear in the dashboard
2. Open WhatsApp on your phone:
   - Go to **Settings** > **Linked Devices**
   - Tap **"Link a Device"**
   - Scan the QR code
3. Wait for the connection to establish

## Evolution API Management

```bash
# Stop Evolution API
make evolution-stop

# Clean Evolution API (removes all data)
make evolution-clean
```

## Available Commands

| Command | Description |
|---------|-------------|
| `make setup` | Install dependencies and create virtual environment |
| `make run` | Run the application |
| `make clean` | Remove virtual environment |
| `make evolution-start` | Start Evolution API |
| `make evolution-stop` | Stop Evolution API |
| `make evolution-clean` | Stop and clean all Evolution API data |

## Troubleshooting

### Evolution API Won't Start

Check if Docker is running:
```bash
docker ps
```

Check Docker Compose logs:
```bash
cd external-services/evolution-api-2.3.6
docker compose logs
```

### QR Code Not Appearing

Restart the Evolution API:
```bash
make evolution-stop
make evolution-start
```

## Additional Resources

- [UV Documentation](https://github.com/astral-sh/uv)
- [Evolution API Documentation](https://doc.evolution-api.com/)
- [Docker Documentation](https://docs.docker.com/)

## License
[Apache License](LICENSE)