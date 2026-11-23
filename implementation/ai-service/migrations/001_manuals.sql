ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS model_code text,
 ADD COLUMN IF NOT EXISTS page_no integer, ADD COLUMN IF NOT EXISTS section text,
 ADD COLUMN IF NOT EXISTS ordinal integer, ADD COLUMN IF NOT EXISTS fault_code text,
 ADD COLUMN IF NOT EXISTS symptom_tags jsonb, ADD COLUMN IF NOT EXISTS user_steps jsonb;
CREATE INDEX IF NOT EXISTS ix_manual_code ON knowledge_chunks(model_code,fault_code);
CREATE UNIQUE INDEX IF NOT EXISTS uq_manual_source ON knowledge_chunks(model_code,file_name,page_no,ordinal);
