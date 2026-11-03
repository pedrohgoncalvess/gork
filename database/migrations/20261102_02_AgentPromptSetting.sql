-- Allow each agent to send user content without its instructions.
-- depends: 20261024_01_EncryptedTextColumns
ALTER TABLE ai.agent ADD COLUMN disable_system_prompt BOOLEAN NOT NULL DEFAULT FALSE;
