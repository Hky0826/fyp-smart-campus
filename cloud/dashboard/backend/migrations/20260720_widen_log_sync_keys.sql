-- Edge modules may have queued logs produced by historical key formats.
-- Keep sync keys unique while allowing current 26-character ULIDs and legacy keys.
ALTER TABLE authentication_logs MODIFY COLUMN sync_key VARCHAR(64) NOT NULL;
ALTER TABLE surveillance_logs MODIFY COLUMN sync_key VARCHAR(64) NOT NULL;