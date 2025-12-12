-- refac media
-- depends: 20251203_02_mAXIh-image-models
CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE "content"."media" ADD COLUMN image_embedding vector(1024) NOT NULL;
ALTER TABLE "content"."media" ADD COLUMN name_embedding vector(1024) NOT NULL;
ALTER TABLE "content"."media" RENAME COLUMN sub_path TO "path";
ALTER TABLE "content"."media" RENAME COLUMN "type" TO format;
ALTER TABLE "content"."media" ADD COLUMN message_id INTEGER NOT NULL;
ALTER TABLE "content"."media" ADD COLUMN name VARCHAR(150) NOT NULL;
ALTER TABLE "content"."media" ADD CONSTRAINT media_message_fk FOREIGN KEY (message_id) REFERENCES "content"."message"(id);


ALTER TABLE "content"."message" DROP COLUMN media_id;
ALTER TABLE "content"."message" RENAME COLUMN sender_id TO user_id;