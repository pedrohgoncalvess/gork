-- image models
-- depends: 20251203_01_esZT9-remember-feat-table

ALTER TABLE "manager"."model" ADD COLUMN image_default BOOLEAN DEFAULT FALSE;
ALTER TABLE "manager"."model" ADD COLUMN audio_default BOOLEAN DEFAULT FALSE;
ALTER TABLE "manager"."model" RENAME COLUMN "default" TO text_default;
ALTER TABLE "manager"."model" DROP COLUMN "audio_input";
INSERT INTO "manager"."model" (name, openrouter_id, input_price, output_price, image_default) VALUES
('Gemini 2.5 Flash Image (Nano Banana)', 'google/gemini-2.5-flash-image', 0.30, 20, true),
('Black Forest Labs: FLUX.2 Pro', 'black-forest-labs/flux.2-pro', 3.66, 3.66, false),
('OpenAI: GPT-5 Image Mini', 'openai/gpt-5-image-mini', 2.5, 8, false);