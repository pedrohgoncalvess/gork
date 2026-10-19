-- Persistent observations scoped to a group or private conversation
-- depends: 20260827_01_ImageReferenceFallback

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE manager.observation (
    id SERIAL PRIMARY KEY,
    group_id INTEGER REFERENCES base."group"(id),
    user_id INTEGER REFERENCES base."user"(id),
    source_message_id INTEGER REFERENCES content.message(id) ON DELETE SET NULL,
    content TEXT NOT NULL CHECK (length(btrim(content)) BETWEEN 1 AND 4000),
    embedding vector(2560),
    embedding_model_id INTEGER REFERENCES ai.model(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    search_document TSVECTOR GENERATED ALWAYS AS (to_tsvector('portuguese', content)) STORED,
    CONSTRAINT observation_scope CHECK ((group_id IS NULL) <> (user_id IS NULL)),
    CONSTRAINT observation_embedding_model CHECK (
        (embedding IS NULL) = (embedding_model_id IS NULL)
    )
);

CREATE INDEX observation_group_scope ON manager.observation (group_id, created_at DESC)
    WHERE group_id IS NOT NULL;
CREATE INDEX observation_dm_scope ON manager.observation (user_id, created_at DESC)
    WHERE group_id IS NULL;
CREATE UNIQUE INDEX observation_group_content ON manager.observation (group_id, md5(content))
    WHERE group_id IS NOT NULL;
CREATE UNIQUE INDEX observation_dm_content ON manager.observation (user_id, md5(content))
    WHERE group_id IS NULL;
CREATE INDEX observation_terms ON manager.observation USING gin (search_document);
CREATE INDEX observation_substrings ON manager.observation USING gin (content gin_trgm_ops);
-- halfvec indexing supports our 2560 dimensions (requires pgvector >= 0.7).
CREATE INDEX observation_similarity ON manager.observation USING hnsw
    ((embedding::halfvec(2560)) halfvec_cosine_ops)
    WHERE embedding IS NOT NULL;
