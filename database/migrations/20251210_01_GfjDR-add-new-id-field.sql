-- add new id field
-- depends: 20251208_01_c99m2-refac-interaction-table

ALTER TABLE "base"."group" ADD COLUMN ext_id UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4();
ALTER TABLE "base"."user" ADD COLUMN ext_id UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4();
ALTER TABLE "content"."message" ADD COLUMN ext_id UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4();
ALTER TABLE "content"."media" ADD COLUMN ext_id UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4();