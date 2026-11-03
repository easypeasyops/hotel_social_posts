-- Public bucket for images being published (app/publishing/buffer.py). Buffer fetches a
-- post's media when the post goes out, possibly days after it was queued, so the URL must
-- not expire: the private hotel-assets bucket's signed URLs would. Only images about to be
-- posted are copied here; they are public on the social network anyway. Reads are public;
-- writes come only from the server's service-role key (no insert policy for anyone else).
insert into storage.buckets (id, name, public)
values ('published-media', 'published-media', true)
on conflict (id) do nothing;
