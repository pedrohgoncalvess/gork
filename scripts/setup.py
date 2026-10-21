"""Create .env and missing secrets once: uv run python -m scripts.setup."""
import base64
import io
from pathlib import Path
import secrets

from dotenv import dotenv_values


def prepare(root: Path):
    target = root / ".env"
    content = target.read_text(encoding="utf-8") if target.exists() else (root / ".env.example").read_text(encoding="utf-8")
    values = dotenv_values(stream=io.StringIO(content))
    generated = {}
    for name in ("WAHA_API_KEY", "WAHA_WEBHOOK_TOKEN", "ADMIN_PASSWORD", "ADMIN_SESSION_SECRET", "MCP_ENCRYPTION_KEY"):
        if not values.get(name):
            generated[name] = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode() if name == "MCP_ENCRYPTION_KEY" else secrets.token_urlsafe(36)
    lines = content.splitlines()
    for name, value in generated.items():
        lines = [line for line in lines if line.split("=", 1)[0].strip() != name]
        lines.append(f"{name}={value}")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return generated


def main():
    generated = prepare(Path(__file__).resolve().parents[1])
    print(".env preparado. Credenciais existentes foram preservadas.")
    if "ADMIN_PASSWORD" in generated:
        print(f"Senha inicial do painel: {generated['ADMIN_PASSWORD']}")
    print("Configure as credenciais de infraestrutura e OPENROUTER_KEY. Suba o Compose e abra /admin para conectar o WhatsApp.")


if __name__ == "__main__":
    main()
