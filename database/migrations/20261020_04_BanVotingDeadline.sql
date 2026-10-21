-- Ten-minute voting, excluding the bot from the eligible electorate.
-- depends: 20261020_03_GroupBan
ALTER TABLE manager.group_ban_poll ALTER COLUMN closes_at
    SET DEFAULT clock_timestamp() + INTERVAL '10 minutes';
UPDATE manager.group_ban_poll SET closes_at=LEAST(closes_at, opened_at + INTERVAL '10 minutes')
    WHERE status IN ('creating','open');

WITH electorate AS (
    SELECT p.id, COALESCE(jsonb_object_agg(e.key, e.value) FILTER (
        WHERE e.key <> ALL(ARRAY[COALESCE(s.phone_number,'') || '@c.us', COALESCE(s.lid,'') || '@lid'])
          AND e.value <> ALL(ARRAY[COALESCE(s.phone_number,'') || '@c.us', COALESCE(s.lid,'') || '@lid'])
    ), '{}'::jsonb) AS members
    FROM manager.group_ban_poll p CROSS JOIN base.app_settings s
    CROSS JOIN LATERAL jsonb_each_text(p.electorate) e
    WHERE s.id=1 AND p.status IN ('creating','open') GROUP BY p.id
)
UPDATE manager.group_ban_poll p SET electorate=e.members,
    member_count=(SELECT count(DISTINCT value) FROM jsonb_each_text(e.members))
FROM electorate e WHERE p.id=e.id AND e.members <> '{}'::jsonb;
