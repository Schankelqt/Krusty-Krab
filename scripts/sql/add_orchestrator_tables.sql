CREATE TABLE IF NOT EXISTS assistant_instances (
  id SERIAL PRIMARY KEY,
  owner_user_id BIGINT NOT NULL,
  name VARCHAR(255) NOT NULL,
  purpose VARCHAR(512) NOT NULL,
  goal_text TEXT,
  template_key VARCHAR(128) NOT NULL,
  route_mode VARCHAR(32) NOT NULL DEFAULT 'auto',
  status VARCHAR(32) NOT NULL DEFAULT 'draft',
  telegram_bot_username VARCHAR(255),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT ck_assistant_instances_route_mode
    CHECK (route_mode IN ('paid_api', 'free_ollama', 'auto')),
  CONSTRAINT ck_assistant_instances_status
    CHECK (status IN ('draft', 'provisioning', 'ready', 'failed', 'archived'))
);
ALTER TABLE assistant_instances ADD COLUMN IF NOT EXISTS goal_text TEXT;
CREATE INDEX IF NOT EXISTS ix_assistant_instances_owner_user_id
  ON assistant_instances (owner_user_id);
CREATE INDEX IF NOT EXISTS ix_assistant_instances_status
  ON assistant_instances (status);

CREATE TABLE IF NOT EXISTS provision_jobs (
  id SERIAL PRIMARY KEY,
  owner_user_id BIGINT NOT NULL,
  assistant_instance_id INTEGER,
  job_type VARCHAR(64) NOT NULL DEFAULT 'create_assistant',
  template_key VARCHAR(128) NOT NULL,
  goal_text TEXT,
  status VARCHAR(32) NOT NULL DEFAULT 'queued',
  error_message TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT ck_provision_jobs_job_type
    CHECK (job_type IN ('create_assistant')),
  CONSTRAINT ck_provision_jobs_status
    CHECK (status IN ('queued', 'running', 'needs_input', 'failed', 'completed'))
);
ALTER TABLE provision_jobs ADD COLUMN IF NOT EXISTS template_key VARCHAR(128);
ALTER TABLE provision_jobs ADD COLUMN IF NOT EXISTS goal_text TEXT;
CREATE INDEX IF NOT EXISTS ix_provision_jobs_owner_user_id
  ON provision_jobs (owner_user_id);
CREATE INDEX IF NOT EXISTS ix_provision_jobs_assistant_instance_id
  ON provision_jobs (assistant_instance_id);
CREATE INDEX IF NOT EXISTS ix_provision_jobs_status_created_at
  ON provision_jobs (status, created_at);

CREATE TABLE IF NOT EXISTS provision_steps (
  id SERIAL PRIMARY KEY,
  job_id INTEGER NOT NULL,
  step_key VARCHAR(128) NOT NULL,
  status VARCHAR(32) NOT NULL DEFAULT 'queued',
  details JSONB,
  error_message TEXT,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  CONSTRAINT ck_provision_steps_status
    CHECK (status IN ('queued', 'running', 'failed', 'completed', 'skipped'))
);
ALTER TABLE provision_steps ADD COLUMN IF NOT EXISTS error_message TEXT;
CREATE INDEX IF NOT EXISTS ix_provision_steps_job_id
  ON provision_steps (job_id);
CREATE INDEX IF NOT EXISTS ix_provision_steps_job_id_step_key
  ON provision_steps (job_id, step_key);
