-- Persistent poll moderation, shared by all workers.
-- depends: 20261020_02_MessageSearch
CREATE TABLE manager.group_ban_poll (
    id BIGSERIAL PRIMARY KEY,
    session TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    command_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    target_aliases JSONB NOT NULL,
    target_name TEXT NOT NULL,
    electorate JSONB NOT NULL,
    member_count INTEGER NOT NULL CHECK (member_count > 0),
    duration_minutes INTEGER NOT NULL CHECK (duration_minutes BETWEEN 1 AND 180),
    poll_id TEXT,
    status TEXT NOT NULL DEFAULT 'creating',
    opened_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    closes_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp() + INTERVAL '15 minutes',
    ban_started_at TIMESTAMPTZ,
    ban_until TIMESTAMPTZ,
    notice_sent BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE (session, command_id),
    UNIQUE (session, poll_id)
);
CREATE UNIQUE INDEX group_ban_pending_target ON manager.group_ban_poll(session, chat_id, target_id)
    WHERE status IN ('creating', 'open');
CREATE INDEX group_ban_active ON manager.group_ban_poll(session, chat_id, ban_until) WHERE status = 'approved';
CREATE TABLE manager.group_ban_vote (
    poll_id BIGINT NOT NULL REFERENCES manager.group_ban_poll(id) ON DELETE CASCADE,
    voter_id TEXT NOT NULL,
    choice TEXT NOT NULL CHECK (choice IN ('Sim', 'Não', '')),
    timestamp BIGINT NOT NULL,
    PRIMARY KEY (poll_id, voter_id)
);
