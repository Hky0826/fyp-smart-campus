-- Shared face embedding model migration. Run once against smart_campus_db.
ALTER TABLE user_face_embeddings
    MODIFY COLUMN model_name ENUM('arcface_mobilefacenet', 'arcface_r50', 'openvc_sface', 'auraface') NOT NULL;

ALTER TABLE users DROP COLUMN username;