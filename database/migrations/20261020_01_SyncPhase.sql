-- Show which synchronization stage is currently running or failed.
-- depends: 20261019_04_Setup
ALTER TABLE base.sync_job ADD COLUMN phase TEXT NOT NULL DEFAULT 'contacts';
