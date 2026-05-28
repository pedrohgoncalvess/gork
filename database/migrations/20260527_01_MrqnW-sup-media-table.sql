-- sup media table
-- depends: 20251221_03_i2N4b-fix-message-media-fk

CREATE TABLE "content"."sup_media" (
    id SERIAL,
    name VARCHAR(50) UNIQUE NOT NULL,
    bucket VARCHAR(50) NOT NULL,
    path VARCHAR(150) NOT NULL,
    type VARCHAR(10) NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),

    CONSTRAINT sup_media_pk PRIMARY KEY (id)
);