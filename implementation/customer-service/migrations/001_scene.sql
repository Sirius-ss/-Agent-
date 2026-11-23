ALTER TABLE conversations ADD COLUMN IF NOT EXISTS service_scene text NOT NULL DEFAULT 'ECOMMERCE',
 ADD COLUMN IF NOT EXISTS service_context jsonb NOT NULL DEFAULT '{}',
 ADD COLUMN IF NOT EXISTS context_version bigint NOT NULL DEFAULT 0;
ALTER TABLE handoffs ADD COLUMN IF NOT EXISTS context_snapshot jsonb NOT NULL DEFAULT '{}';
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='ck_conversation_scene' AND conrelid='conversations'::regclass) THEN
 ALTER TABLE conversations ADD CONSTRAINT ck_conversation_scene CHECK(service_scene IN ('ECOMMERCE','APPLIANCE_SERVICE') AND context_version>=0);
 END IF;
END $$;

DROP INDEX IF EXISTS uq_open_conversation_per_user;
DROP INDEX IF EXISTS uq_collecting_turn_per_conversation;
CREATE UNIQUE INDEX IF NOT EXISTS uq_collect_turn ON conversation_turn(conversation_id) WHERE status='COLLECTION';
