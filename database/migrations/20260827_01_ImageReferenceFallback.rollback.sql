-- image reference limits and multi-reference fallback model
-- depends: 20260826_02_DisabledCommands

UPDATE "ai"."model"
SET metadata = (COALESCE(metadata, '{}'::JSONB) - 'image_fallback_models')
WHERE openrouter_id = 'x-ai/grok-imagine-image-quality';

DELETE FROM "ai"."model"
WHERE openrouter_id = 'google/gemini-3-pro-image'
  AND NOT EXISTS (
      SELECT 1 FROM "ai"."agent"
      WHERE model_id = "ai"."model".id
  )
  AND NOT EXISTS (
      SELECT 1 FROM "ai"."model_conversation"
      WHERE model_id = "ai"."model".id
  )
  AND NOT EXISTS (
      SELECT 1 FROM "ai"."model_price"
      WHERE model_id = "ai"."model".id
  );
