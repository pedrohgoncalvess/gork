-- Record the actual decision time, including early voting and panel actions.
-- depends: 20261020_04_BanVotingDeadline
ALTER TABLE manager.group_ban_poll ADD COLUMN finished_at TIMESTAMPTZ;
UPDATE manager.group_ban_poll
    SET finished_at=COALESCE(ban_started_at, LEAST(closes_at, clock_timestamp()))
    WHERE status IN ('approved','rejected','revoked','cancelled','invalid');
CREATE INDEX group_ban_cooldown ON manager.group_ban_poll(session, chat_id, finished_at);
