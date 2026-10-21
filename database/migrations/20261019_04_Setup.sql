-- Runtime setup, shared by all application workers.
-- depends: 20261019_02_AdminAgentSettings
CREATE TABLE base.app_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    principal_user_id INTEGER REFERENCES base."user"(id),
    phone_number TEXT,
    lid TEXT,
    test_mode BOOLEAN NOT NULL DEFAULT false,
    test_number TEXT
);
INSERT INTO base.app_settings (id) VALUES (1);
CREATE TABLE base.sync_job (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    status TEXT NOT NULL DEFAULT 'running',
    contacts INTEGER NOT NULL DEFAULT 0,
    messages INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX one_active_sync ON base.sync_job ((true)) WHERE status = 'running';
ALTER TABLE content.message ADD COLUMN chat_user_id INTEGER REFERENCES base."user"(id);
CREATE INDEX message_chat_user ON content.message (chat_user_id, created_at);
