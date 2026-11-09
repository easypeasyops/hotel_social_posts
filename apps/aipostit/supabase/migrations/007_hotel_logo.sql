-- A hotel's logo (app/hotel_logo.py): a WebP in the private hotel-assets bucket at
-- hotel-logos/{hotel_id}.webp, set by an operator or the hotel's admin. logo_version is the
-- upload's time (epoch seconds): pages show the logo only when it is set, and put it in the
-- logo's URL so a browser never shows an older one from its cache. Null: no logo, initials.
-- Safe for the version already running, which neither selects it by name nor writes it.
alter table hotels add column logo_version bigint;
