-- Retain incoming message data after moderation has already deleted it.
-- depends: 20261020_05_BanCooldown
CREATE TABLE manager.group_ban_deletion (
    id BIGSERIAL PRIMARY KEY,
    session TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    sender_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    deleted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE(session, chat_id, provider_id)
);
