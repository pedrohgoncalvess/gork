-- feature black list
-- depends: 20260601_01_RNSAs-structured-output

CREATE TABLE "base"."black_list" (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    features TEXT[] NOT NULL DEFAULT '{}',
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,

    CONSTRAINT black_list_user_fk
        FOREIGN KEY (user_id)
        REFERENCES "base"."user"(id)
        ON DELETE CASCADE
);

CREATE UNIQUE INDEX black_list_active_user_uidx
    ON "base"."black_list" (user_id)
    WHERE deleted_at IS NULL;
