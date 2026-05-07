-- big refactor
-- depends: 20251221_01_7rSRX-favorite-message

ALTER TABLE "manager"."agent" DROP COLUMN "model_id" INTEGER;

DROP TABLE "manager"."model_conversation";