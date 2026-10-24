-- Ciphertext envelopes exceed the original plaintext VARCHAR limits.
-- depends: 20261020_06_BanDeletions

ALTER TABLE base."user"
    ALTER COLUMN src_id TYPE TEXT,
    ALTER COLUMN phone_number TYPE TEXT,
    ALTER COLUMN name TYPE TEXT;

ALTER TABLE base."group"
    ALTER COLUMN name TYPE TEXT;

ALTER TABLE content.media
    ALTER COLUMN name TYPE TEXT;

-- Deliberately no narrowing rollback: encrypted values may exceed old limits.
