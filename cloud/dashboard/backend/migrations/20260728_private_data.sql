ALTER TABLE chatbot_queries ADD COLUMN query_hash VARCHAR(64) NULL;
ALTER TABLE chatbot_queries ADD COLUMN query_length INT NULL;
ALTER TABLE chatbot_queries ADD COLUMN query_category VARCHAR(32) NULL;
