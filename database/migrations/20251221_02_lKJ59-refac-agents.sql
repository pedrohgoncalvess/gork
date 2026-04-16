-- expensive control
-- depends: 20251221_01_7rSRX-favorite-message

ALTER TABLE "manager"."agent" ADD COLUMN "model_id" INTEGER;
ALTER TABLE "manager"."agent" ADD CONSTRAINT "agent_model_fk" FOREIGN KEY (model_id) REFERENCES "manager"."model"(id);

CREATE TABLE "manager"."model_conversation" (
    id SERIAL,
    user_id INTEGER,
    group_id INTEGER,
    agent_id INTEGER NOT NULL,
    model_id INTEGER NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),

    CONSTRAINT model_conversation_pk PRIMARY KEY (id),
    CONSTRAINT model_conversation_user_fk FOREIGN KEY (user_id) REFERENCES "base"."user"(id),
    CONSTRAINT model_conversation_group_fk FOREIGN KEY (group_id) REFERENCES "base"."group"(id),
    CONSTRAINT model_conversation_agent_fk FOREIGN KEY (agent_id) REFERENCES "manager"."agent"(id),
    CONSTRAINT model_conversation_model_fk FOREIGN KEY (model_id) REFERENCES "manager"."model"(id)
);