ALTER TABLE conversations ADD COLUMN IF NOT EXISTS thread_key varchar(100) NOT NULL DEFAULT '';
CREATE UNIQUE INDEX IF NOT EXISTS uq_open_scene_thread ON conversations(user_id,service_scene,thread_key)
 WHERE mode IN ('AI','HUMAN','QUEUED');
DROP INDEX IF EXISTS uq_open_scene;
