-- remember feat table
-- depends: 20241210_01_LQSl5

CREATE TABLE "manager"."remember" (
    id SERIAL,
    user_id INTEGER,
    group_id INTEGER,
    remember_at TIMESTAMP NOT NULL,
    message TEXT,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'America/Sao_Paulo'),
    updated_at TIMESTAMP,
    deleted_at TIMESTAMP,

    CONSTRAINT remember_pk PRIMARY KEY (id),
    CONSTRAINT remember_user_fk FOREIGN KEY (user_id) REFERENCES "base"."user"(id),
    CONSTRAINT remember_group_fk FOREIGN KEY (group_id) REFERENCES "base"."group"(id)
);