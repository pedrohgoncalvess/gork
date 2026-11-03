-- Allow one unban poll per active ban.
-- depends: 20261024_01_EncryptedTextColumns
ALTER TABLE manager.group_ban_poll
    ADD COLUMN poll_type TEXT NOT NULL DEFAULT 'ban' CHECK (poll_type IN ('ban', 'unban')),
    ADD COLUMN ban_poll_id BIGINT REFERENCES manager.group_ban_poll(id) ON DELETE CASCADE,
    DROP CONSTRAINT group_ban_poll_duration_minutes_check,
    ADD CONSTRAINT group_ban_poll_duration_minutes_check CHECK (
        (poll_type = 'ban' AND duration_minutes BETWEEN 1 AND 180)
        OR (poll_type = 'unban' AND duration_minutes = 0)
    );
CREATE UNIQUE INDEX group_unban_once_per_ban ON manager.group_ban_poll(ban_poll_id)
    WHERE ban_poll_id IS NOT NULL AND status <> 'failed';
