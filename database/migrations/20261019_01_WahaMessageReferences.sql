-- Persist WAHA references across workers and restarts without rewriting history.
-- depends: 20261001_01_ConversationObservations
CREATE TABLE content.waha_message_reference (
    session TEXT NOT NULL,
    message_id TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    media JSONB,
    PRIMARY KEY (session, message_id)
);
