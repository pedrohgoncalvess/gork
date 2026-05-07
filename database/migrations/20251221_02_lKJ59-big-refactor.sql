-- big refactor
-- depends: 20251221_01_7rSRX-favorite-message

CREATE TABLE "manager"."model_conversation" (
    id SERIAL,
    user_id INTEGER,
    group_id INTEGER,
    agent_id INTEGER NOT NULL,
    model_id INTEGER NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),

    CONSTRAINT model_conversation_pk PRIMARY KEY (id),
    CONSTRAINT model_conversation_user_fk FOREIGN KEY (user_id) REFERENCES "base"."user"(id),
    CONSTRAINT model_conversation_group_fk FOREIGN KEY (group_id) REFERENCES "base"."group"(id),
    CONSTRAINT model_conversation_agent_fk FOREIGN KEY (agent_id) REFERENCES "manager"."agent"(id),
    CONSTRAINT model_conversation_model_fk FOREIGN KEY (model_id) REFERENCES "manager"."model"(id)
);

ALTER TABLE "content"."message" ADD COLUMN quoted_message_id INTEGER;
ALTER TABLE "content"."message" ADD CONSTRAINT quoted_message_message_fk FOREIGN KEY (quoted_message_id) REFERENCES "content"."message"(id);

ALTER TABLE "base"."group" ADD COLUMN auto_message BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE "content"."media" RENAME TO "dep_media";

CREATE TABLE "content"."media" (
    id SERIAL,
    ext_id UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4(),
    name VARCHAR(150) NOT NULL,
    bucket VARCHAR(30) NOT NULL,
    "path" VARCHAR(200) NOT NULL,
    "type" VARCHAR(20), --audio, image, sticker, profile pic, video
    "size" DECIMAL,
    description TEXT,
    description_embedding VECTOR(2560),
    hash BYTEA NOT NULL UNIQUE,
    phash BIGINT,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),

    CONSTRAINT n_media_pk PRIMARY KEY (id)
);

ALTER TABLE "content"."message" ADD COLUMN media_id INTEGER;
ALTER TABLE "content"."message" ADD CONSTRAINT message_media_fk FOREIGN KEY (media_id) REFERENCES "content"."media"(id);

ALTER TABLE "base"."user" ADD COLUMN "last_att_profile_pic" TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo');

CREATE TABLE "manager"."embedding" (
    id SERIAL,
    term TEXT NOT NULL,
    embedding VECTOR(2560) NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),

    CONSTRAINT n_embedding_pk PRIMARY KEY (id)
);

UPDATE "manager"."model" SET text_default = false;

INSERT INTO "manager"."model" (name, openrouter_id, input_price, output_price, text_default)
VALUES (
        'DeepSeek: DeepSeek V4 Flash',
        'deepseek/deepseek-v4-flash',
        0.14,
        0.28,
        true
       );

CREATE TABLE "manager"."collection" (
    id SERIAL,
    user_id INTEGER NOT NULL,
    group_id INTEGER,
    message_id INTEGER NOT NULL,
    context TEXT,
    embedding VECTOR(2560) NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),

    CONSTRAINT embedding_pk PRIMARY KEY (id)
);
