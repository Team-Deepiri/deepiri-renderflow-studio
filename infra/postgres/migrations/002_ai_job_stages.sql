create table if not exists ai_job_stages (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references ai_jobs(id) on delete cascade,
  stage_name text not null,
  stage_order int not null,
  status text not null default 'pending',
  log_text text,
  started_at timestamptz,
  ended_at timestamptz
);

create index if not exists idx_ai_job_stages_job on ai_job_stages(job_id);
