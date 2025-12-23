-- favorite message
-- depends: 20251212_02_sLdXG-add-profile-pic-path

ALTER TABLE "content"."message" ADD COLUMN is_favorite BOOLEAN DEFAULT FALSE NOT NULL;