create extension if not exists "pgcrypto";

create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  email text not null unique,
  display_name text not null,
  role text not null default 'editor',
  created_at timestamptz not null default now()
);

create table if not exists projects (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references users(id),
  name text not null,
  fps_num int not null default 24,
  fps_den int not null default 1,
  sample_rate int not null default 48000,
  ai_enabled boolean not null default true,
  settings_jsonb jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists assets (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete cascade,
  kind text not null,
  uri text not null,
  sha256 text not null,
  duration_ms bigint,
  meta_jsonb jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists sequences (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete cascade,
  name text not null,
  start_tc text not null default '00:00:00:00',
  duration_ticks bigint not null default 0,
  resolution_w int not null default 1920,
  resolution_h int not null default 1080,
  created_at timestamptz not null default now()
);

create table if not exists tracks (
  id uuid primary key default gen_random_uuid(),
  sequence_id uuid not null references sequences(id) on delete cascade,
  track_type text not null,
  lane_index int not null,
  name text not null,
  muted boolean not null default false,
  solo boolean not null default false,
  created_at timestamptz not null default now()
);

create table if not exists clips (
  id uuid primary key default gen_random_uuid(),
  track_id uuid not null references tracks(id) on delete cascade,
  asset_id uuid not null references assets(id),
  in_tick bigint not null,
  out_tick bigint not null,
  src_in_tick bigint not null default 0,
  speed_ratio numeric(10, 4) not null default 1.0,
  transform_jsonb jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists ai_jobs (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete cascade,
  requested_by uuid references users(id),
  mode text not null,
  prompt text not null,
  status text not null default 'queued',
  model_ref text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
