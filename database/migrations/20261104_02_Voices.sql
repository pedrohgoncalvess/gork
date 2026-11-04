-- Local references for stateless voice cloning.
-- depends: 20261104_01_AgentModels

CREATE TABLE content.voice (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'pt',
    start_seconds DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (start_seconds >= 0),
    duration_seconds DOUBLE PRECISION NOT NULL DEFAULT 180 CHECK (duration_seconds > 0 AND duration_seconds <= 180),
    source_url TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
