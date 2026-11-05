-- Hotels
create table hotels (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  slug        text not null unique,
  location    text not null,
  description text,
  tier        text not null default 'standard' check (tier in ('standard', 'growth', 'premium')),
  channels    text[] not null default array['instagram', 'facebook'],
  contact_email text not null,
  buffer_profiles jsonb default '{}',  -- {"instagram": "buffer_profile_id", ...}
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

-- Assets
create table assets (
  id             uuid primary key default gen_random_uuid(),
  hotel_id       uuid not null references hotels(id) on delete cascade,
  filename       text not null,
  category       text not null check (category in ('room','pool','food','exterior','lobby','beach','other')),
  storage_path   text not null,
  storage_url    text,
  status         text not null default 'pending' check (status in ('pending','processing','ready','failed')),
  created_at     timestamptz not null default now(),
  processed_at   timestamptz
);

-- Content drafts
create table content_drafts (
  id                uuid primary key default gen_random_uuid(),
  hotel_id          uuid not null references hotels(id) on delete cascade,
  channel           text not null,
  status            text not null default 'pending_review'
                    check (status in ('pending_review','approved','rejected','scheduled','published','failed')),
  body_tr           text not null,
  asset_ids         uuid[] default '{}',
  operator_feedback text,
  scheduled_at      timestamptz,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

-- Translations
create table content_translations (
  id            uuid primary key default gen_random_uuid(),
  draft_id      uuid not null references content_drafts(id) on delete cascade,
  language      text not null check (language in ('en','de','ru','ar')),
  body          text not null,
  translated_at timestamptz not null default now(),
  unique (draft_id, language)
);

-- Publish log
create table publish_log (
  id                uuid primary key default gen_random_uuid(),
  draft_id          uuid not null references content_drafts(id) on delete cascade,
  hotel_id          uuid not null references hotels(id) on delete cascade,
  channel           text not null,
  buffer_update_id  text,
  status            text not null default 'scheduled' check (status in ('scheduled','published','failed')),
  published_at      timestamptz,
  created_at        timestamptz not null default now()
);

-- Auto-update updated_at
create or replace function update_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger hotels_updated_at before update on hotels
  for each row execute function update_updated_at();

create trigger content_drafts_updated_at before update on content_drafts
  for each row execute function update_updated_at();
