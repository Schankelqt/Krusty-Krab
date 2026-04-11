-- После обновления модели User (agent_*). Выполнить на существующей БД:
ALTER TABLE users ADD COLUMN IF NOT EXISTS agent_display_name VARCHAR(128);
ALTER TABLE users ADD COLUMN IF NOT EXISTS agent_instructions TEXT;
