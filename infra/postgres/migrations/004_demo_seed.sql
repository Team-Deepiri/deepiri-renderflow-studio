-- Demo user for local development (deterministic UUID)
insert into users (id, email, display_name, role)
values (
  '00000000-0000-4000-8000-000000000001',
  'studio@renderflow.local',
  'Renderflow Studio',
  'admin'
)
on conflict (email) do nothing;
