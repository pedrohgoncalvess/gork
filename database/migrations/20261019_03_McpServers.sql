-- MCP configuration and credential-free invocation audit.
-- depends: 20261019_02_AdminAgentSettings
CREATE TABLE ai.mcp_server (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    url TEXT NOT NULL,
    transport TEXT NOT NULL CHECK (transport IN ('streamable_http', 'sse')),
    enabled BOOLEAN NOT NULL DEFAULT true,
    settings_encrypted TEXT NOT NULL,
    tool_names JSONB NOT NULL DEFAULT '[]',
    tools JSONB NOT NULL DEFAULT '[]',
    timeout_seconds INTEGER NOT NULL DEFAULT 20 CHECK (timeout_seconds BETWEEN 3 AND 60),
    user_id INTEGER REFERENCES base."user"(id),
    group_id INTEGER REFERENCES base."group"(id),
    checked_at TIMESTAMPTZ,
    last_error TEXT,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    CHECK (user_id IS NULL OR group_id IS NULL)
);
CREATE TABLE ai.mcp_call (
    id BIGSERIAL PRIMARY KEY,
    server_id INTEGER REFERENCES ai.mcp_server(id),
    tool_name TEXT NOT NULL,
    user_id INTEGER REFERENCES base."user"(id),
    group_id INTEGER REFERENCES base."group"(id),
    message_id INTEGER REFERENCES content.message(id),
    success BOOLEAN NOT NULL,
    duration_ms INTEGER NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX mcp_call_server_time ON ai.mcp_call(server_id, inserted_at DESC);
