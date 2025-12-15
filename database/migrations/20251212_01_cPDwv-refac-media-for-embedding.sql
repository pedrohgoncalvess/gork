-- refac media for embedding
-- depends: 20251210_01_GfjDR-add-new-id-field

ALTER TABLE "manager"."model" ADD COLUMN embedding_default BOOLEAN NOT NULL DEFAULT FALSE;

INSERT INTO "manager"."model"(name, openrouter_id, "input_price", output_price, embedding_default) VALUES
('Qwen3 Embedding 4B', 'qwen/qwen3-embedding-4b ', 0.02, 0, true);

DELETE FROM "content"."media";

ALTER TABLE "content"."media" ADD COLUMN description TEXT NOT NULL;
ALTER TABLE "content"."media" DROP COLUMN name_embedding;
ALTER TABLE "content"."media" DROP COLUMN image_embedding;
ALTER TABLE "content"."media" ADD COLUMN description_embedding vector(1280) NOT NULL;
ALTER TABLE "content"."media" ADD COLUMN image_embedding vector(1280) NOT NULL;
