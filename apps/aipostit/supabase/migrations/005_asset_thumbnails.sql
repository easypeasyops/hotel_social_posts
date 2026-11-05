-- A small WebP copy of each photo (app/assets/thumbnails.py), for the pages that list photos.
-- Null until the worker has made one: files that aren't photos, and photos uploaded before.
alter table assets add column thumbnail_path text;
