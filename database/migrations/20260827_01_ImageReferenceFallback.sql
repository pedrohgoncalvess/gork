-- image reference limits and multi-reference fallback model
-- depends: 20260826_02_DisabledCommands

UPDATE "ai"."model"
SET metadata = COALESCE(metadata, '{}'::JSONB) || jsonb_build_object(
    'image', jsonb_build_object(
        'supported_parameters', jsonb_build_object(
            'input_references', jsonb_build_object('type', 'range', 'min', 0, 'max', 3)
        )
    ),
    'image_fallback_models', jsonb_build_array('google/gemini-3-pro-image')
)
WHERE openrouter_id = 'x-ai/grok-imagine-image-quality';

INSERT INTO "ai"."model" (name, openrouter_id, metadata)
SELECT
    'Google: Nano Banana Pro (Gemini 3 Pro Image)',
    'google/gemini-3-pro-image',
    jsonb_build_object(
        'image', jsonb_build_object(
            'supported_parameters', jsonb_build_object(
                'input_references', jsonb_build_object('type', 'range', 'min', 0, 'max', 14)
            )
        ),
        'image_fallback_priority', 1
    )
WHERE NOT EXISTS (
    SELECT 1 FROM "ai"."model"
    WHERE openrouter_id = 'google/gemini-3-pro-image'
);

UPDATE "ai"."model"
SET metadata = COALESCE(metadata, '{}'::JSONB) || jsonb_build_object(
    'image', jsonb_build_object(
        'supported_parameters', jsonb_build_object(
            'input_references', jsonb_build_object('type', 'range', 'min', 0, 'max', 14)
        )
    ),
    'image_fallback_priority', 1
)
WHERE openrouter_id = 'google/gemini-3-pro-image';
