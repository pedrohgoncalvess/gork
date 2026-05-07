-- fix message media fk
-- depends: 20251221_02_lKJ59-big-refactor

ALTER TABLE "content"."message" DROP CONSTRAINT IF EXISTS message_media_fk;

ALTER TABLE "content"."message"
ADD CONSTRAINT message_media_fk
FOREIGN KEY (media_id) REFERENCES "content"."dep_media"(id);
