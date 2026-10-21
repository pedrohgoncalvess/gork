-- Index message text for the administration semantic search.
-- depends: 20261020_01_SyncPhase
ALTER TABLE content.message ADD COLUMN content_embedding vector(2560);
