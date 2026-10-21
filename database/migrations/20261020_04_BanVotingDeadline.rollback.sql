-- Existing shortened deadlines remain unchanged on rollback.
ALTER TABLE manager.group_ban_poll ALTER COLUMN closes_at
    SET DEFAULT clock_timestamp() + INTERVAL '15 minutes';
