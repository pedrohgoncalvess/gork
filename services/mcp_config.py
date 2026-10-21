"""Encrypted MCP settings and deterministic argument handling."""
from copy import deepcopy
import json
import re
from urllib.parse import parse_qsl, urlsplit

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict, Field, model_validator
from utils import get_env_var


class McpInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=3000)
    url: str = Field(min_length=8, max_length=2000)
    transport: str = "streamable_http"
    enabled: bool = True
    headers: dict[str, str] = Field(default_factory=dict, max_length=50)
    params: dict[str, str | int | float | bool] = Field(default_factory=dict, max_length=50)
    fixed_arguments: dict[str, dict] = Field(default_factory=dict, max_length=200)
    tool_names: list[str] = Field(default_factory=list, max_length=200)
    timeout_seconds: int = Field(default=20, ge=3, le=60)
    user_id: int | None = Field(default=None, gt=0)
    group_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_config(self):
        self.name, self.description, self.url = self.name.strip(), self.description.strip(), self.url.strip()
        if not self.name or not self.description:
            raise ValueError("Informe nome e descrição do MCP.")
        parsed = urlsplit(self.url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("Use uma URL HTTP(S), sem credenciais embutidas ou fragmento.")
        if self.transport not in ("streamable_http", "sse"):
            raise ValueError("Transporte MCP inválido.")
        parameter_names = {key.lower() for key in self.params}.union(key.lower() for key, _ in parse_qsl(parsed.query))
        if parameter_names & {"session_id", "sessionid"}:
            raise ValueError("Não configure o identificador de sessão do protocolo como parâmetro fixo.")
        if self.user_id is not None and self.group_id is not None:
            raise ValueError("Escolha um usuário ou grupo.")
        protected = {"host", "content-length", "content-type", "accept", "connection", "transfer-encoding", "mcp-session-id", "mcp-protocol-version", "mcp-method", "mcp-name"}
        seen = set()
        for key, value in self.headers.items():
            if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key) or key.lower() in protected or key.lower() in seen:
                raise ValueError("Header inválido, duplicado ou reservado pelo protocolo MCP.")
            if "\r" in value or "\n" in value or not value.isascii():
                raise ValueError("Valores de headers devem usar ASCII sem quebras de linha.")
            seen.add(key.lower())
        if len(json.dumps({"headers": self.headers, "params": self.params, "fixed_arguments": self.fixed_arguments})) > 64000:
            raise ValueError("Configuração MCP muito grande.")
        return self


def cipher() -> Fernet:
    value = get_env_var("MCP_ENCRYPTION_KEY")
    if not value:
        raise ValueError("Configure MCP_ENCRYPTION_KEY no ambiente do Gork.")
    try:
        return Fernet(value.encode())
    except (ValueError, TypeError):
        raise ValueError("MCP_ENCRYPTION_KEY inválida.") from None


def encrypt_settings(data: McpInput) -> str:
    settings = {key: getattr(data, key) for key in ("headers", "params", "fixed_arguments")}
    return cipher().encrypt(json.dumps(settings).encode()).decode()


def decrypt_settings(value: str) -> dict:
    try:
        return json.loads(cipher().decrypt(value.encode()))
    except (InvalidToken, json.JSONDecodeError):
        raise ValueError("Não foi possível ler a configuração MCP. Verifique a chave de criptografia.") from None


def fixed_merge(arguments: dict, fixed: dict) -> dict:
    result = deepcopy(arguments)
    for key, value in fixed.items():
        result[key] = fixed_merge(result.get(key, {}) if isinstance(result.get(key), dict) else {}, value) if isinstance(value, dict) else deepcopy(value)
    return result


def public_schema(schema: dict, fixed: dict) -> dict:
    """Hide fixed values, including their schemas/defaults, from model arguments."""
    schema = deepcopy(schema)
    for key, value in fixed.items():
        properties = schema.get("properties", {})
        if isinstance(value, dict) and isinstance(properties.get(key), dict) and properties[key].get("type") == "object":
            properties[key] = public_schema(properties[key], value)
            if not properties[key].get("required"):
                schema["required"] = [name for name in schema.get("required", []) if name != key]
        else:
            properties.pop(key, None)
            schema["required"] = [name for name in schema.get("required", []) if name != key]
    return schema
