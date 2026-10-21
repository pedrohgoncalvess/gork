"""Official SDK clients for remote MCPs (modern HTTP and legacy SSE)."""
import asyncio
from contextlib import asynccontextmanager
from functools import partial
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx2
from mcp import Client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from jsonschema.validators import validator_for
from services.mcp_log_filter import protect_logs, secrets_in_context


def connection_url(url: str, params: dict) -> str:
    parsed = urlsplit(url)
    values = dict(parse_qsl(parsed.query, keep_blank_values=True))
    values.update({key: str(value).lower() if isinstance(value, bool) else str(value) for key, value in params.items()})
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(values), ""))


@asynccontextmanager
async def connect(server, settings: dict):
    token = protect_logs(settings)
    try:
        async with _connect(server, settings) as client:
            yield client
    finally:
        secrets_in_context.reset(token)


@asynccontextmanager
async def _connect(server, settings: dict):
    url = connection_url(server.url, settings.get("params", {}))
    seconds = server.timeout_seconds
    async with asyncio.timeout(seconds):
        if server.transport == "sse":
            # SSE advertises a separate POST endpoint carrying its own session_id.
            # Client-level params would replace that query. Merge at request time.
            async def fixed_params(request):
                request.url = request.url.copy_merge_params(dict(parse_qsl(urlsplit(url).query)))
            transport = sse_client(url, headers=settings.get("headers", {}), timeout=seconds, sse_read_timeout=seconds,
                                   httpx_client_factory=partial(httpx2.AsyncClient, event_hooks={"request": [fixed_params]}))
            async with Client(transport, mode="legacy", read_timeout_seconds=seconds, cache=None) as client:
                yield client
        else:
            async with httpx2.AsyncClient(headers=settings.get("headers", {}), timeout=seconds) as http_client:
                transport = streamable_http_client(url, http_client=http_client)
                async with Client(transport, read_timeout_seconds=seconds, cache=None) as client:
                    yield client


def check_schema(schema: dict):
    """Keep schema validation local; never fetch remote JSON Schema references."""
    def visit(value, depth=0):
        if depth > 60:
            raise ValueError("Schema MCP muito profundo.")
        if isinstance(value, dict):
            for key in ("$ref", "$dynamicRef", "$recursiveRef"):
                if key in value and not str(value[key]).startswith("#"):
                    raise ValueError("Referências externas de schema não são suportadas.")
            for child in value.values():
                visit(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                visit(child, depth + 1)
    visit(schema)
    validator_for(schema).check_schema(schema)


async def list_client_tools(client) -> list[dict]:
    tools, seen, cursor = [], set(), None
    for _ in range(20):
        page = await client.list_tools(cursor=cursor)
        for tool in page.tools:
            data = tool.model_dump(mode="json", by_alias=True)
            schema = data.get("inputSchema", {})
            check_schema(schema)
            tools.append({"name": data["name"], "description": data.get("description") or "",
                          "inputSchema": schema, "annotations": data.get("annotations")})
        cursor = page.next_cursor
        if not cursor:
            return tools
        if cursor in seen or len(tools) > 500:
            break
        seen.add(cursor)
    raise ValueError("Catálogo MCP excedeu o limite de paginação.")


async def discover(server, settings: dict) -> list[dict]:
    async with connect(server, settings) as client:
        return await list_client_tools(client)


async def call_tool(server, settings: dict, name: str, arguments: dict):
    async with connect(server, settings) as client:
        tools = await list_client_tools(client)
        tool = next((item for item in tools if item["name"] == name), None)
        if tool is None:
            raise ValueError("Ferramenta MCP não está mais disponível.")
        validator_for(tool["inputSchema"])(tool["inputSchema"]).validate(arguments)
        return await client.call_tool(name, arguments, read_timeout_seconds=server.timeout_seconds)
