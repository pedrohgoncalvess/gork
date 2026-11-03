-- depends: 20261024_01_EncryptedTextColumns
DROP INDEX IF EXISTS manager.group_unban_once_per_ban;
DELETE FROM manager.group_ban_poll WHERE poll_type = 'unban';
ALTER TABLE manager.group_ban_poll
    DROP CONSTRAINT group_ban_poll_duration_minutes_check,
    ADD CONSTRAINT group_ban_poll_duration_minutes_check CHECK (duration_minutes BETWEEN 1 AND 180),
    DROP COLUMN ban_poll_id,
    DROP COLUMN poll_type;
