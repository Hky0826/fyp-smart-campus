CREATE TABLE IF NOT EXISTS face_auth_challenges (
  challenge_id VARCHAR(64) PRIMARY KEY,
  device_id VARCHAR(100) NOT NULL,
  user_id INT NOT NULL,
  expires_at DATETIME NOT NULL,
  used_at DATETIME NULL,
  match_passed BOOLEAN NOT NULL DEFAULT FALSE,
  liveness_passed BOOLEAN NOT NULL DEFAULT FALSE,
  pad_model_version VARCHAR(100) NULL,
  pad_score FLOAT NULL,
  CONSTRAINT fk_face_challenge_device FOREIGN KEY (device_id) REFERENCES devices(device_id) ON DELETE CASCADE,
  CONSTRAINT fk_face_challenge_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
