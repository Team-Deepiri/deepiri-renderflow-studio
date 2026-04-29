-- Extended studio: effects, 3D scene graph, AI artifacts, render queue, audit

create table if not exists asset_versions (
  id uuid primary key default gen_random_uuid(),
  asset_id uuid not null references assets(id) on delete cascade,
  version_no int not null default 1,
  uri text not null,
  derivation_type text not null default 'import',
  parent_version_id uuid references asset_versions(id),
  created_at timestamptz not null default now(),
  unique (asset_id, version_no)
);

create table if not exists clip_effects (
  id uuid primary key default gen_random_uuid(),
  clip_id uuid not null references clips(id) on delete cascade,
  effect_type text not null,
  order_idx int not null default 0,
  params_jsonb jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_clip_effects_clip on clip_effects(clip_id);

create table if not exists scenes (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete cascade,
  name text not null,
  unit_scale double precision not null default 1.0,
  up_axis text not null default 'Y',
  created_at timestamptz not null default now()
);

create table if not exists scene_nodes (
  id uuid primary key default gen_random_uuid(),
  scene_id uuid not null references scenes(id) on delete cascade,
  parent_id uuid references scene_nodes(id) on delete cascade,
  node_type text not null,
  transform_jsonb jsonb not null default '{}'::jsonb,
  payload_jsonb jsonb not null default '{}'::jsonb
);

create index if not exists idx_scene_nodes_scene on scene_nodes(scene_id);

create table if not exists animation_curves (
  id uuid primary key default gen_random_uuid(),
  target_node_id uuid not null references scene_nodes(id) on delete cascade,
  property_path text not null,
  interpolation text not null default 'linear',
  keys_jsonb jsonb not null default '[]'::jsonb
);

create table if not exists ai_job_artifacts (
  id uuid primary key default gen_random_uuid(),
  job_id uuid not null references ai_jobs(id) on delete cascade,
  asset_id uuid references assets(id),
  artifact_type text not null,
  confidence double precision,
  created_at timestamptz not null default now()
);

create index if not exists idx_ai_job_artifacts_job on ai_job_artifacts(job_id);

create table if not exists render_jobs (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete cascade,
  sequence_id uuid references sequences(id) on delete set null,
  preset text not null default 'h264_1080p',
  status text not null default 'queued',
  output_uri text,
  metrics_jsonb jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  ended_at timestamptz
);

create index if not exists idx_render_jobs_project on render_jobs(project_id);

create table if not exists audit_events (
  id uuid primary key default gen_random_uuid(),
  project_id uuid references projects(id) on delete set null,
  actor_id uuid references users(id),
  event_type text not null,
  payload_jsonb jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_audit_project on audit_events(project_id);
