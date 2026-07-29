-- Security remediation migration. Apply in a maintenance window before
-- enabling mandatory signed device requests.
ALTER TABLE devices ADD COLUMN device_secret_ciphertext TEXT NULL;
ALTER TABLE devices ADD COLUMN credential_rotated_at DATETIME NULL;
ALTER TABLE jwt_sessions ADD COLUMN session_uuid VARCHAR(64) NULL;
ALTER TABLE jwt_sessions ADD COLUMN jti VARCHAR(64) NULL;
ALTER TABLE jwt_sessions ADD COLUMN principal_type VARCHAR(32) NOT NULL DEFAULT 'ADMIN';
-- Force re-authentication after JWT/database credential rotation.
UPDATE jwt_sessions SET is_revoked = 1;
CREATE UNIQUE INDEX uq_jwt_sessions_session_uuid ON jwt_sessions(session_uuid);
CREATE UNIQUE INDEX uq_jwt_sessions_jti ON jwt_sessions(jti);
CREATE TABLE IF NOT EXISTS device_request_nonces (
  device_id VARCHAR(100) NOT NULL,
  nonce VARCHAR(128) NOT NULL,
  expires_at DATETIME NOT NULL,
  PRIMARY KEY (device_id, nonce),
  CONSTRAINT fk_device_nonce_device FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE CASCADE
);
