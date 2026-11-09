-- Staff invites: one row per invite, the authority its token points at (the token carries
-- the hotel and the row's id). Every invite names one email and works once. Its status is
-- derived, not stored: accepted (accepted_at), revoked (revoked_at), expired (expires_at
-- passed), else pending. last_sent_at is set only when an email went out, so null is
-- "email not sent". The app reads and writes this table with the service-role key only; RLS
-- with no policies keeps the anon and authenticated keys out, as for hotel_members.
create table staff_invites (
  id                uuid primary key default gen_random_uuid(),
  hotel_id          uuid not null references hotels (id) on delete cascade,
  role              text not null
                    check (role in ('hotel_admin', 'content_moderator', 'content_creator')),
  email             text not null check (email = lower(email)),
  valid_days        int not null default 7 check (valid_days between 1 and 30),
  invited_by_email  text not null,
  created_at        timestamptz not null default now(),
  expires_at        timestamptz not null,
  last_sent_at      timestamptz,
  send_count        int not null default 0 check (send_count >= 0),
  accepted_at       timestamptz,
  revoked_at        timestamptz,
  revoked_by_email  text,
  check (accepted_at is null or revoked_at is null)
);

-- A hotel's invites, newest first (the dashboard's hotel page and /hotel/staff).
create index staff_invites_hotel_id_created_at on staff_invites (hotel_id, created_at desc);

-- When an invite ended, for the purge after the hotel's retention: accepted and revoked come
-- before expiry, so the earliest of the three is the end (least ignores nulls).
create index staff_invites_ended_at on staff_invites (least(accepted_at, revoked_at, expires_at));

alter table staff_invites enable row level security;

-- How many days an ended invite's row (and so its email) is kept before the purge deletes it.
alter table hotels
  add column invite_retention_days int not null default 90
  check (invite_retention_days between 7 and 180);
