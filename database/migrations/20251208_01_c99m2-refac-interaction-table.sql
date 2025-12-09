-- refac interaction table
-- depends: 20251205_01_nhuzb-refac-media

DROP TABLE "manager"."interaction";

CREATE TABLE "manager"."interaction" (
    id SERIAL,
    model_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    group_id INTEGER,
    command_id INTEGER,
    agent_id INTEGER,
    user_prompt TEXT NOT NULL,
    system_behavior TEXT,
    response TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),

    CONSTRAINT interaction_pk PRIMARY KEY (id),
    CONSTRAINT interaction_model_fk FOREIGN KEY (model_id) REFERENCES "manager"."model"(id),
    CONSTRAINT interaction_group_fk FOREIGN KEY (group_id) REFERENCES "base"."group"(id),
    CONSTRAINT interaction_command_fk FOREIGN KEY (command_id) REFERENCES "manager"."command"(id),
    CONSTRAINT interaction_agent_fk FOREIGN KEY (agent_id) REFERENCES "manager"."agent"(id),
    CONSTRAINT interaction_user_fk FOREIGN KEY (user_id) REFERENCES "base"."user"(id)
);