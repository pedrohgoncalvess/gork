-- versioned OpenRouter model pricing and AI-owned entities
-- depends: 20260813_01_BkLst-image-black-list

ALTER TABLE "ai"."model" ADD COLUMN input_price NUMERIC(10, 2);
ALTER TABLE "ai"."model" ADD COLUMN output_price NUMERIC(10, 2);

UPDATE "ai"."model" AS model
SET
    input_price = (
        SELECT price.prompt_price * 1000000
        FROM "ai"."model_price" AS price
        WHERE price.model_id = model.id
        ORDER BY price.fetched_at DESC, price.id DESC
        LIMIT 1
    ),
    output_price = (
        SELECT price.completion_price * 1000000
        FROM "ai"."model_price" AS price
        WHERE price.model_id = model.id
        ORDER BY price.fetched_at DESC, price.id DESC
        LIMIT 1
    );

ALTER TABLE "ai"."interaction" ADD COLUMN model_id INTEGER;

UPDATE "ai"."interaction" AS interaction
SET model_id = price.model_id
FROM "ai"."model_price" AS price
WHERE price.id = interaction.model_price_id;

ALTER TABLE "ai"."interaction" ALTER COLUMN model_id SET NOT NULL;
ALTER TABLE "ai"."interaction"
    ADD CONSTRAINT interaction_model_fk
    FOREIGN KEY (model_id) REFERENCES "ai"."model"(id);
ALTER TABLE "ai"."interaction" DROP COLUMN model_price_id;
ALTER TABLE "ai"."interaction" DROP COLUMN actual_cost;

DROP TABLE "ai"."model_price";

DELETE FROM "ai"."model_conversation"
WHERE agent_id IN (SELECT id FROM "ai"."agent" WHERE name = 'video-generation');
UPDATE "ai"."interaction" SET agent_id = NULL
WHERE agent_id IN (SELECT id FROM "ai"."agent" WHERE name = 'video-generation');
DELETE FROM "ai"."agent" WHERE name = 'video-generation';
DELETE FROM "ai"."model" AS model
WHERE model.openrouter_id = 'bytedance/seedance-2.0-fast'
  AND NOT EXISTS (
      SELECT 1 FROM "ai"."interaction" AS interaction
      WHERE interaction.model_id = model.id
  )
  AND NOT EXISTS (
      SELECT 1 FROM "ai"."model_conversation" AS conversation
      WHERE conversation.model_id = model.id
  )
  AND NOT EXISTS (
      SELECT 1 FROM "ai"."agent" AS agent
      WHERE agent.model_id = model.id
  );

ALTER TABLE "ai"."model" DROP COLUMN metadata;

ALTER TABLE "ai"."interaction" SET SCHEMA "manager";
ALTER TABLE "ai"."model_conversation" SET SCHEMA "manager";
ALTER TABLE "ai"."agent" SET SCHEMA "manager";
ALTER TABLE "ai"."model" SET SCHEMA "manager";

DROP SCHEMA "ai";
