-- fix message media fk
-- depends: 20251221_02_lKJ59-big-refactor

ALTER TABLE "content"."message" DROP CONSTRAINT IF EXISTS message_media_fk;

UPDATE "content"."message" AS m
SET media_id = NULL
WHERE media_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1
    FROM "content"."media" AS media
    WHERE media.id = m.media_id
  );

ALTER TABLE "content"."message"
ADD CONSTRAINT message_media_fk
FOREIGN KEY (media_id) REFERENCES "content"."media"(id);
