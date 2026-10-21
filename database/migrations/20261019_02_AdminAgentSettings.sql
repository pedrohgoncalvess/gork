-- Preserve models and prompts edited through the administration panel on restart.
-- depends: 20261019_01_WahaMessageReferences
ALTER TABLE ai.agent ADD COLUMN model_managed BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE ai.agent ADD COLUMN prompt_managed BOOLEAN NOT NULL DEFAULT false;
