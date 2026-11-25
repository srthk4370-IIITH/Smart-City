-- Smart City Edge fog (owner 2026-11-20): REPORTS ONLY. No raw sensor readings ever go here.
-- Run once in Supabase dashboard -> SQL Editor -> New query -> paste -> Run.
-- Boards use the publishable (anon) key: they may only INSERT/UPSERT. Reading is for signed-in users (fleet page).

create table if not exists public.boards (
  board_id    text primary key,
  site        text,
  first_seen  timestamptz default now(),
  last_seen   timestamptz default now()
);

create table if not exists public.incident_reports (
  board_id     text not null,
  incident_id  text not null,
  revision     int  not null default 0,
  created_at   timestamptz,
  updated_at   timestamptz default now(),
  severity     text,
  title        text,
  domains      text[],
  location     text,
  label        text,
  root_cause   text,
  checklist    jsonb,     -- steps with done/not-needed ticks
  report       jsonb,     -- the operator report (no raw readings)
  state        text,      -- running / done / closed ...
  primary key (board_id, incident_id, revision)
);

create table if not exists public.decisions (
  id           bigint generated always as identity primary key,
  board_id     text not null,
  incident_id  text not null,
  at           timestamptz not null,
  actor        text,
  action       text,      -- ack / dismiss / close / reopen / undo / confirm_dismiss ...
  outcome      text,
  note         text
);

create table if not exists public.board_health (
  id            bigint generated always as identity primary key,
  board_id      text not null,
  at            timestamptz not null default now(),
  uptime_s      bigint,
  restarts_7d   int,
  disk_used_pct real,
  temp_c        real,
  app_version   text,
  agent_model   text,
  reasoner_model text,
  open_critical int,
  open_warning  int,
  status        jsonb
);

create index if not exists incident_reports_board_time on public.incident_reports (board_id, updated_at desc);
create index if not exists decisions_board_time on public.decisions (board_id, at desc);
create index if not exists board_health_board_time on public.board_health (board_id, at desc);

alter table public.boards           enable row level security;
alter table public.incident_reports enable row level security;
alter table public.decisions        enable row level security;
alter table public.board_health     enable row level security;

-- boards (anon key): insert only (append a new revision row; duplicates ignored), never read, update or delete
drop policy if exists boards_ins on public.boards;
create policy boards_ins on public.boards for insert to anon with check (true);
drop policy if exists reports_ins on public.incident_reports;
create policy reports_ins on public.incident_reports for insert to anon with check (true);
drop policy if exists decisions_ins on public.decisions;
create policy decisions_ins on public.decisions for insert to anon with check (true);
drop policy if exists health_ins on public.board_health;
create policy health_ins on public.board_health for insert to anon with check (true);

-- fleet page (signed-in users): read everything
drop policy if exists boards_read on public.boards;
create policy boards_read on public.boards for select to authenticated using (true);
drop policy if exists reports_read on public.incident_reports;
create policy reports_read on public.incident_reports for select to authenticated using (true);
drop policy if exists decisions_read on public.decisions;
create policy decisions_read on public.decisions for select to authenticated using (true);
drop policy if exists health_read on public.board_health;
create policy health_read on public.board_health for select to authenticated using (true);

-- the board appends rows (ON CONFLICT DO NOTHING); last_seen comes from board_health
grant insert on public.boards, public.incident_reports, public.decisions, public.board_health to anon;
grant select on public.boards, public.incident_reports, public.decisions, public.board_health to authenticated;
