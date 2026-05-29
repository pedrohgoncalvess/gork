-- 
-- depends:

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE SCHEMA "manager";

CREATE TABLE "manager"."model" (
    id SERIAL,
    name TEXT NOT NULL,
    openrouter_id TEXT NOT NULL,
    audio_input BOOLEAN DEFAULT FALSE,
    input_price NUMERIC(10, 2),
    output_price NUMERIC(10, 2),
    "default" BOOLEAN NOT NULL DEFAULT FALSE,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),

    CONSTRAINT model_pk PRIMARY KEY (id)
);

INSERT INTO "manager"."model" (name, openrouter_id, "default", input_price, output_price) VALUES
('DeepSeek Chat V3.1', 'deepseek/deepseek-chat-v3.1', true, 0.27, 1.00),
('GPT-4', 'openai/gpt-4', false, 30.00, 60.00),
('Qwen 2.5 72B', 'qwen/qwen-2.5-72b-instruct', false, 0.12, 0.39),
('Qwen2.5 Coder 7B', 'qwen/qwen2.5-coder-7b-instruct', false, 0.03, 0.09);

INSERT INTO "manager"."model"(name, openrouter_id, "default", "input_price", output_price, audio_input) VALUES
('Gemini 2.0 Flash Lite', 'google/gemini-2.0-flash-lite-001', true, 0.075, 0.3, true);

CREATE TABLE "manager"."agent" (
    id SERIAL,
    name VARCHAR(50) NOT NULL UNIQUE,
    prompt TEXT NOT NULL,
    model_id INTEGER NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),

    CONSTRAINT agent_pk PRIMARY KEY (id),
    CONSTRAINT agent_model_fk FOREIGN KEY (model_id) REFERENCES "manager"."model"(id)
);

CREATE SCHEMA "content";

CREATE TABLE "content"."media" (
    id SERIAL,
    bucket VARCHAR(30) NOT NULL,
    sub_path VARCHAR(200) NOT NULL,
    "type" VARCHAR(20), --audio, image, sticker, profile pic, video
    "size" DECIMAL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),
    updated_at TIMESTAMP,
    deleted_at TIMESTAMP,

    CONSTRAINT media_pk PRIMARY KEY (id)
);

CREATE SCHEMA "base";

CREATE TABLE "base"."user" (
    id SERIAL,
    src_id VARCHAR(100) UNIQUE NOT NULL,
    phone_number VARCHAR(20),
    name VARCHAR(255),
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),
    updated_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT user_pk PRIMARY KEY (id)
);

CREATE TABLE "base"."group" (
    id SERIAL,
    src_id VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(255),
    description TEXT,
    profile_image_url TEXT,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),
    updated_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT group_pk PRIMARY KEY (id)
);

CREATE TABLE "manager"."command" (
    id SERIAL,
    command VARCHAR(50) NOT NULL,
    user_id INTEGER NOT NULL,
    group_id INTEGER,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),

    CONSTRAINT command_pk PRIMARY KEY (id),
    CONSTRAINT command_user_fk FOREIGN KEY (user_id) REFERENCES "base"."user"(id),
    CONSTRAINT command_group_fk FOREIGN KEY (group_id) REFERENCES "base"."group"(id)
);

CREATE TABLE "manager"."interaction" (
    id SERIAL,
    model_id INTEGER NOT NULL,
    interaction_id INTEGER,
    command_id INTEGER,
    agent_id INTEGER,
    sender VARCHAR(10) NOT NULL,
    content TEXT NOT NULL,
    tokens INTEGER NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),

    CONSTRAINT interaction_pk PRIMARY KEY (id),
    CONSTRAINT interaction_model_fk FOREIGN KEY (model_id) REFERENCES "manager"."model"(id),
    CONSTRAINT interaction_command_fk FOREIGN KEY (command_id) REFERENCES "manager"."command"(id),
    CONSTRAINT interaction_agent_fk FOREIGN KEY (agent_id) REFERENCES "manager"."agent"(id),
    CONSTRAINT interaction_interaction_fk FOREIGN KEY (interaction_id) REFERENCES "manager"."interaction"(id)
);

CREATE TABLE "base"."white_list" (
    id SERIAL,
    sender_type VARCHAR(5) NOT NULL,
    sender_id INTEGER NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at TIMESTAMP,

    CONSTRAINT white_list_pk PRIMARY KEY (id)
);

CREATE TABLE "content"."message" (
    id SERIAL,
    message_id VARCHAR(255) NOT NULL UNIQUE,
    sender_id INTEGER,
    media_id INTEGER,
    group_id INTEGER,
    content TEXT,
    created_at TIMESTAMP NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),
    updated_at TIMESTAMP,
    deleted_at TIMESTAMP,

    CONSTRAINT message_pk PRIMARY KEY (id),
    CONSTRAINT message_user_fk FOREIGN KEY (sender_id) REFERENCES "base"."user"(id),
    CONSTRAINT message_group_fk FOREIGN KEY (group_id) REFERENCES "base"."group"(id),
    CONSTRAINT message_media_fk FOREIGN KEY (media_id) REFERENCES "content"."media"(id)
);

CREATE TABLE "content"."mention" (
    id SERIAL,
    message_id INTEGER NOT NULL,
    mentioned_message_id INTEGER NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),

    CONSTRAINT mention_pk PRIMARY KEY (id),
    CONSTRAINT mention_message_fk FOREIGN KEY (message_id) REFERENCES "content"."message"(id),
    CONSTRAINT mentioned_message_fk FOREIGN KEY (mentioned_message_id) REFERENCES "content"."message"(id)
);