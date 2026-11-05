-- Hotel staff roles. hotel_admin: everything below, plus the hotel's details and its staff.
-- content_moderator: upload, edit, delete and decide the hotel's files and drafts.
-- content_creator: upload, and see the files and drafts without changing them.
-- The default keeps today's staff, and accounts made by an image older than roles, able to
-- do what they could before.
alter table hotel_members
  add column role text not null default 'hotel_admin'
  check (role in ('hotel_admin', 'content_moderator', 'content_creator'));
