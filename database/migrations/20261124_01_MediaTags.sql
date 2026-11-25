-- depends: 20261104_02_Voices

CREATE TABLE content.media_tag (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES base."user"(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    source_message_id TEXT NOT NULL,
    command_message_id TEXT NOT NULL UNIQUE,
    marked_at TIMESTAMP NOT NULL,
    consumed_at TIMESTAMPTZ,
    claim_id UUID,
    claim_until TIMESTAMPTZ
);

CREATE INDEX media_tag_latest_idx
    ON content.media_tag (user_id, kind, marked_at DESC, id DESC);
