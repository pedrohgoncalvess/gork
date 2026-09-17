-- temporarily disabled commands by global, group and/or user scope
-- depends: 20260826_01_AiModelPricing

CREATE TABLE "manager"."disabled_command" (
    id SERIAL PRIMARY KEY,
    command VARCHAR(50) NOT NULL,
    user_id INTEGER,
    group_id INTEGER,
    message TEXT NOT NULL DEFAULT 'Este comando está temporariamente desativado.',
    disabled_until TIMESTAMPTZ,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ,

    CONSTRAINT disabled_command_user_fk
        FOREIGN KEY (user_id) REFERENCES "base"."user"(id) ON DELETE CASCADE,
    CONSTRAINT disabled_command_group_fk
        FOREIGN KEY (group_id) REFERENCES "base"."group"(id) ON DELETE CASCADE
);

CREATE INDEX disabled_command_lookup_idx
    ON "manager"."disabled_command" (
        LOWER(LTRIM(command, '!')),
        user_id,
        group_id,
        inserted_at DESC
    )
    WHERE deleted_at IS NULL;
