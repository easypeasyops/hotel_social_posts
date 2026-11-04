-- Hotel staff: a Supabase account that belongs to one hotel. Staff see and act on that hotel
-- only (app/staff.py); operators are marked by app_metadata.role instead and are not here.
-- The app reads and writes this table with the service-role key only; RLS with no policies
-- keeps the anon and authenticated keys out.
create table hotel_members (
  user_id     uuid primary key references auth.users (id) on delete cascade,
  hotel_id    uuid not null references hotels (id) on delete cascade,
  email       text not null,
  created_at  timestamptz not null default now()
);

create index hotel_members_hotel_id on hotel_members (hotel_id);

alter table hotel_members enable row level security;
