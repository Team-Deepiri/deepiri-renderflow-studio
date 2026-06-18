-- 006_guardrails.sql — Guardrail decisions + consent records

create table if not exists guardrail_decisions (
  id uuid primary key default gen_random_uuid(),
  job_id uuid references ai_jobs(id) on delete cascade,
  gate text not null,           -- policy | prompt | plan | generation | output
  verdict text not null,        -- allow | block | escalate | redact
  reason_code text,             -- e.g. SAFETY_BLOCK, RATE_LIMIT, AI_DISABLED
  score double precision,
  details_jsonb jsonb not null default '{}',
  created_at timestamptz not null default now()
);

create index if not exists idx_guardrail_job on guardrail_decisions(job_id);
create index if not exists idx_guardrail_verdict on guardrail_decisions(verdict);

create table if not exists ai_consent_records (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete cascade,
  subject_label text not null,
  asset_id uuid references assets(id),
  granted_by uuid references users(id),
  scope text not null default 'likeness',
  expires_at timestamptz,
  created_at timestamptz not null default now()
);
