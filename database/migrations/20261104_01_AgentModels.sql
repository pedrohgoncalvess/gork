-- Resolve text, audio and image models through their agents.
-- depends: 20261102_02_AgentPromptSetting

ALTER TABLE ai.model
    DROP COLUMN text_default,
    DROP COLUMN audio_default,
    DROP COLUMN image_default;
