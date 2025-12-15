-- add profile pic path
-- depends: 20251212_01_cPDwv-refac-media-for-embedding

ALTER TABLE "base"."user" ADD COLUMN profile_pic_path TEXT;