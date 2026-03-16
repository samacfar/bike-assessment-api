-- Run this in your Supabase SQL editor to create required tables.

create table if not exists assessments (
  id          uuid primary key,
  session_id  uuid not null,
  assessment  jsonb not null,
  image_count integer not null default 1,
  created_at  timestamptz not null default now()
);

create table if not exists challenges (
  id                  uuid primary key,
  assessment_id       uuid not null references assessments(id),
  component_name      text not null,
  previous_assessment jsonb,
  revised_assessment  jsonb,
  created_at          timestamptz not null default now()
);

-- Index for fast lookup by session
create index if not exists idx_assessments_session_id on assessments(session_id);
create index if not exists idx_challenges_assessment_id on challenges(assessment_id);
