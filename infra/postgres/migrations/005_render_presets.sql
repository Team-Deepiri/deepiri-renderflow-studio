-- Render presets and export configuration

create table if not exists render_presets (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  container text not null default 'mp4',
  video_codec text not null default 'h264',
  audio_codec text not null default 'aac',
  video_bitrate_kbps int,
  audio_bitrate_kbps int,
  resolution_w int not null default 1920,
  resolution_h int not null default 1080,
  fps_num int not null default 24,
  fps_den int not null default 1,
  created_at timestamptz not null default now()
);

insert into render_presets (name, container, video_codec, video_bitrate_kbps, resolution_w, resolution_h)
values ('h264_1080p', 'mp4', 'h264', 8000, 1920, 1080)
on conflict (name) do nothing;

insert into render_presets (name, container, video_codec, video_bitrate_kbps, resolution_w, resolution_h)
values ('h264_4k', 'mp4', 'h264', 35000, 3840, 2160)
on conflict (name) do nothing;

insert into render_presets (name, container, video_codec, resolution_w, resolution_h)
values ('prores_422', 'mov', 'prores_422', 1920, 1080)
on conflict (name) do nothing;

create table if not exists project_settings (
  project_id uuid primary key references projects(id) on delete cascade,
  auto_save_interval_secs int not null default 60,
  default_preset_id uuid references render_presets(id),
  proxy_res_w int not null default 854,
  proxy_res_h int not null default 480,
  cache_dir text,
  updated_at timestamptz not null default now()
);

create table if not exists user_sessions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id),
  project_id uuid references projects(id),
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  client_info_jsonb jsonb not null default '{}'::jsonb
);

create index if not exists idx_user_sessions_user on user_sessions(user_id);
create index if not exists idx_user_sessions_project on user_sessions(project_id);