create extension if not exists "pgcrypto";

create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  email text not null unique,
  display_name text not null,
  role text not null default 'editor',
  avatar_url text,
  settings_jsonb jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists projects (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references users(id),
  name text not null,
  fps_num int not null default 24,
  fps_den int not null default 1,
  sample_rate int not null default 48000,
  resolution_w int not null default 1920,
  resolution_h int not null default 1080,
  ai_enabled boolean not null default true,
  settings_jsonb jsonb not null default '{}'::jsonb,
  template_id uuid references projects(id),
  version int not null default 1,
  archived boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now());

create table if not exists project_collaborators (
  project_id uuid not null references projects(id) on delete cascade,
  user_id uuid not null references users(id),
  permission text not null default 'edit',
  joined_at timestamptz not null default now(),
  primary key (project_id, user_id));

create table if not exists assets (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete cascade,
  kind text not null,
  name text not null,
  uri text not null,
  sha256 text,
  file_size_bytes bigint,
  duration_ms bigint,
  meta_jsonb jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now());

create table if not exists sequences (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete cascade,
  name text not null,
  start_tc text not null default '00:00:00:00',
  duration_ticks bigint not null default 0,
  resolution_w int not null default 1920,
  resolution_h int not null default 1080,
  color text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now());

create table if not exists tracks (
  id uuid primary key default gen_random_uuid(),
  sequence_id uuid not null references sequences(id) on delete cascade,
  track_type text not null,
  lane_index int not null,
  name text not null,
  muted boolean not null default false,
  solo boolean not null default false,
  locked boolean not null default false,
  height int not null default 60,
  color text,
  created_at timestamptz not null default now());

create table if not exists clips (
  id uuid primary key default gen_random_uuid(),
  track_id uuid not null references tracks(id) on delete cascade,
  asset_id uuid not null references assets(id),
  name text,
  in_tick bigint not null default 0,
  out_tick bigint not null default 0,
  src_in_tick bigint not null default 0,
  speed_ratio numeric(10, 4) not null default 1.0,
  time_remap_enabled boolean not null default false,
  transform_jsonb jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now());

create table if not exists markers (
  id uuid primary key default gen_random_uuid(),
  sequence_id uuid not null references sequences(id) on delete cascade,
  time_tick bigint not null,
  label text not null,
  color text,
  marker_type text not null default 'note',
  created_at timestamptz not null default now());

create table if not exists render_jobs (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete cascade,
  sequence_id uuid references sequences(id),
  preset text not null,
  output_uri text,
  status text not null default 'pending',
  progress int not null default 0,
  error_message text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now());

create table if not exists ai_jobs (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete cascade,
  requested_by uuid references users(id),
  mode text not null,
  prompt text not null,
  status text not null default 'queued',
  model_ref text,
  stage text,
  result_asset_id uuid references assets(id),
  error_message text,
  retry_count int not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  completed_at timestamptz);

create index if not exists idx_projects_owner on projects(owner_id);
create index if not exists idx_projects_archived on projects(archived) where archived = false;
create index if not exists idx_assets_project on assets(project_id);
create index if not exists idx_assets_kind on assets(kind);
create index if not exists idx_sequences_project on sequences(project_id);
create index if not exists idx_tracks_sequence on tracks(sequence_id);
create index if not exists idx_clips_track on clips(track_id);
create index if not exists idx_clips_timeline on clips(in_tick, out_tick);
create index if not exists idx_markers_sequence on markers(sequence_id, time_tick);
create index if not exists idx_ai_jobs_project on ai_jobs(project_id);
create index if not exists idx_ai_jobs_status on ai_jobs(status);
create index if not exists idx_render_jobs_project on render_jobs(project_id);
create index if not exists idx_render_jobs_status on render_jobs(status);
