-- structured output
-- depends: 20260527_01_MrqnW-sup-media-table

ALTER TABLE manager.agent ADD COLUMN IF NOT EXISTS response_format TEXT;