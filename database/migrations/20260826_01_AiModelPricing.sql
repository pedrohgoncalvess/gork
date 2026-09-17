-- versioned OpenRouter model pricing and AI-owned entities
-- depends: 20260813_01_BkLst-image-black-list

CREATE SCHEMA IF NOT EXISTS "ai";

ALTER TABLE "manager"."model" SET SCHEMA "ai";
ALTER TABLE "manager"."agent" SET SCHEMA "ai";
ALTER TABLE "manager"."model_conversation" SET SCHEMA "ai";
ALTER TABLE "manager"."interaction" SET SCHEMA "ai";

ALTER TABLE "ai"."model"
    ADD COLUMN metadata JSONB NOT NULL DEFAULT '{}'::JSONB;

INSERT INTO "ai"."model" (name, openrouter_id)
SELECT 'ByteDance: Seedance 2.0 Fast', 'bytedance/seedance-2.0-fast'
WHERE NOT EXISTS (
    SELECT 1 FROM "ai"."model"
    WHERE openrouter_id = 'bytedance/seedance-2.0-fast'
);

CREATE TABLE "ai"."model_price" (
    id SERIAL,
    model_id INTEGER NOT NULL,
    prompt_price NUMERIC(30, 18),
    completion_price NUMERIC(30, 18),
    request_price NUMERIC(30, 18),
    image_price NUMERIC(30, 18),
    web_search_price NUMERIC(30, 18),
    internal_reasoning_price NUMERIC(30, 18),
    input_cache_read_price NUMERIC(30, 18),
    input_cache_write_price NUMERIC(30, 18),
    pricing JSONB NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT model_price_pk PRIMARY KEY (id),
    CONSTRAINT model_price_model_fk FOREIGN KEY (model_id) REFERENCES "ai"."model"(id)
);

CREATE INDEX model_price_model_fetched_idx
    ON "ai"."model_price" (model_id, fetched_at DESC, id DESC);

-- Existing values were stored in USD per million tokens. OpenRouter's API and
-- model_price store USD per token/request/unit.
INSERT INTO "ai"."model_price" (
    model_id,
    prompt_price,
    completion_price,
    pricing
)
SELECT
    id,
    input_price / 1000000,
    output_price / 1000000,
    jsonb_build_object(
        'prompt', (input_price / 1000000)::TEXT,
        'completion', (output_price / 1000000)::TEXT
    )
FROM "ai"."model";

ALTER TABLE "ai"."interaction" ADD COLUMN model_price_id INTEGER;
ALTER TABLE "ai"."interaction" ADD COLUMN actual_cost NUMERIC(30, 18);

UPDATE "ai"."interaction" AS interaction
SET model_price_id = price.id
FROM "ai"."model_price" AS price
WHERE price.model_id = interaction.model_id;

ALTER TABLE "ai"."interaction" ALTER COLUMN model_price_id SET NOT NULL;
ALTER TABLE "ai"."interaction"
    ADD CONSTRAINT interaction_model_price_fk
    FOREIGN KEY (model_price_id) REFERENCES "ai"."model_price"(id);
ALTER TABLE "ai"."interaction" DROP COLUMN model_id;

ALTER TABLE "ai"."model" DROP COLUMN input_price;
ALTER TABLE "ai"."model" DROP COLUMN output_price;
