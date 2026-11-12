# Spec: staff invite tracking

Status: decided (Emrah, 2026-11-09), to build next, before the reject-feedback PR. Effort: M.

## Problem

An invite is a signed token and nothing else (`app/auth/upload_tokens.py`): no row in
`supabase/migrations/`. So neither the operator nor a hotel admin can see who was invited,
whether they joined, or whether an invite is still live, and nobody can take one back: the
only revoke is rotating `SECRET_KEY`, which also ends every upload link (ARCHITECTURE,
"Invite links can't be revoked one by one"). Today's link invite works like a password for
7 days for anyone holding it. Emrah hit this himself; no hotel has asked yet (none pays).

**Who:** the operator (dashboard hotel page, `app/dashboard.py`) who invites a hotel's first
admin, and the hotel admin (`/hotel/staff`, `app/staff.py`) who invites the rest.

## What changes

**Every invite names one email and works once.** No more anyone-with-the-link invites. The
two invite forms on each page become one: email, role, valid for (days), and one button,
**Send invite**. The backend records the invite, makes its link and emails it. Only that
address can sign up with it, as email invites already work (`POST /signup` refuses another
address, 403).

- **The email fails** (SMTP error): the invite is still recorded and stays pending; the page
  says the email couldn't be sent, and the row shows "email not sent".
- **No SMTP** (local dev, or `inviteEmail` off): the same form records the invite as "email
  not sent". The feature never depends on mail being set up.

Both pages list the hotel's **Invites** under the members (dashboard in English,
`/hotel/staff` in Turkish): email, role, invited by, made, expires, status, and for a
pending invite its **link with a copy button**, so it can also go by WhatsApp, say. Status
is one of **pending**, **accepted** (date), **expired**, **revoked**; "email not sent" is a
mark on a pending row, not a status. Accepted, expired and revoked rows show no link.
Showing live links is safe: only the operator and the hotel's admin see the list, and they
could make an invite anyway. Actions, for the operator on any hotel and for a hotel admin on
their own hotel's, including invites the operator made (moderators and creators see none of
this, as today):

- **Revoke** (pending): it stops working at once, and its link leaves the table; `/signup`
  shows the existing "invalid or expired" message.
- **Resend** (pending or expired, needs SMTP): emails it again, valid for the same number
  of days from now; it is also how a failed email is retried. The page shows the last send
  and the count.
- **Change role** (pending): whoever accepts gets the new role.

## Expiry and retention

- **Expiry is per invite**, chosen when it is made: default 7 days, 1 to 30. A per-hotel
  default isn't needed: the form starts at 7 and invites are rare. Not editable afterwards;
  Resend is how a lapsed invite gets new time.
- **Retention is per hotel**: how many days an invite's row (and so its email) is kept after
  it ends (accepted, revoked or expired): default 90, 7 to 180. Set on the dashboard's hotel
  edit form (operator) and on `/hotel/details` (hotel admin), through `HotelUpdate`.
- **Deletion is scheduled**: a new task, `tasks.purge_ended_invites`, deletes rows ended
  longer ago than their hotel's retention. A new daily CronJob `purge-invites` in
  `deploy/service/values.yaml` queues it, as `sync-buffer` does, and `staging.yaml` turns it
  off as it does the others (staging shares prod's Supabase). The Job-failure alert already
  covers any failed Job.

## How it works

The invite row becomes the authority; the token only points at it. A new token purpose
(`staff-invite-record`) carries the hotel and the invite's id, signed as today, expiring
with the row at signing time. `/signup` (`app/auth/signup.py`) takes role and email from the
row and refuses a revoked, accepted or expired one. Revoke and change role are one update,
the table's link is re-derived from the id when the page renders, and the database never
holds a usable link.

**Invites sent before the feature** carry no id and aren't listed. `/signup` keeps accepting
the old purposes, multi-use links included, until the last one expires: 7 days after the
release that records invites (PR 3) reaches prod. The list says so with the date; PR 9 then
drops them.

## Data

`staff_invites` (migration `006`, RLS on, no policies, service role only, as
`hotel_members`): `id` (uuid, in the token), `hotel_id` (cascade), `role` (checked), `email`
(lower case, required), `valid_days`, `invited_by_email`, `created_at`, `expires_at`,
`last_sent_at` (set only when an email went out, so null is "email not sent"; the SMTP
error stays in the log, not the row), `send_count`, `accepted_at`, `revoked_at`,
`revoked_by_email`. Status is derived, not stored. Plus `hotels.invite_retention_days` (default 90, checked 7 to 180).
`hotel_members` doesn't change: with one person per invite, `accepted_at` and the email say
who joined. Both changes only add, so the running version is unaffected; apply before
either environment deploys.

## Out of scope

Changing an invite's email or expiry (revoke and make a new one); a per-hotel expiry
default; inviting an existing account (stays SQL, RUNBOOK); reminder emails; more than
Gmail's ~500 recipients a day (Resend counts toward it); an audit of member changes.

## Risks

- **Personal data.** Invitees who never join leave an email behind; the purge bounds it.
  Guess, not legal advice: KVKK likely expects a retention limit like this; check the
  bounds before a hotel relies on them.
- **Staging writes to prod's data:** invites tested on staging show in prod's lists. Test on
  a test hotel only, and say so in RUNBOOK.
- **Old multi-use links** keep working for up to 7 days after the cutover.
- **Resend as spam** hurts the Gmail account's standing; the count is on the page. Add a
  cooldown only if it's abused.

## How we'll know it works

- Emrah answers "did X join, is that invite live?" from the page, with no SQL.
- Revoked, accepted, expired and wrong-email sign-ups each fail at `/signup` (tests, then by
  hand on staging with a test hotel).
- A pilot hotel's admin uses Revoke or Resend without asking Emrah (ask them).
- Rows past retention are gone the day after (check once in SQL); after the cutover date no
  old-purpose token works and ARCHITECTURE's "can't be revoked" line is gone.

## PR stack

About 200 lines each; `main` works after each; ARCHITECTURE/RUNBOOK change in the same PR.
None touches `deploy/envs/prod.yaml`, so all can auto-merge.

1. **Migration `006`**: `staff_invites` and `hotels.invite_retention_days`. No behaviour
   change; data model, RUNBOOK migration list. (~80)
2. **Sign-up honours recorded invites**: `/signup` accepts the new purpose, reads the row,
   sets `accepted_at`. Dormant: nothing issues such tokens yet. (~170)
3. **Send invite records it, with an email and an expiry**: one `create_invite` in
   `app/hotels/invites.py` records the row, then emails it when SMTP is set up; a failed or
   skipped send leaves it pending with no `last_sent_at`. Each page's two forms become one
   (email, role, days, **Send invite**). Starts the 7-day cutover. The biggest: split per
   page if it passes ~250. (~220)
4. **Invite table** on both pages: status, "email not sent", and each pending invite's
   link with a copy button. Until PR 10, a failed email is sent on by copying the link.
   (~200)
5. **Revoke**, both pages; the design-limit line says "old links until <date>". (~120)
6. **Retention setting** on the dashboard's hotel form and `/hotel/details`. (~100)
7. **`tasks.purge_ended_invites`**, with tests and a RUNBOOK line for running it by hand.
   (~120)
8. **`purge-invites` CronJob** in `deploy/service/values.yaml`, off in `staging.yaml`;
   RUNBOOK's CronJob list. (~40)
9. **Drop the pre-tracking invite purposes** after the cutover date (2026-11-16). (~60)
10. **Resend and change role** of an invite. Waits until someone needs it. (~200)

## Decisions (Emrah, 2026-11-09)

1. Old invites run out on their own (at most 7 days); `SECRET_KEY` isn't rotated.
2. Expiry is set per invite when it's made, by the operator or that hotel's admin: 7 days by
   default, 1 to 30. Resend gives it the same number of days again.
3. Every invite names one email and works once; no multi-use links.
4. A hotel admin can revoke or change invites the operator made.
5. PRs 1 to 8 (retention included) are built next, before the reject-feedback PR; Resend and
   change role wait.
6. Retention is per hotel, set by the operator or the hotel's admin: 90 days by default, 7
   to 180, enforced by a daily purge.
7. One button, **Send invite**: no separate "Create link" and "Send email". The table shows
   each pending invite's link with a copy button, for sending it another way.
8. A failed email still records the invite, pending and marked "email not sent", with its
   link in the table.
9. Without SMTP the form still records the invite, as "email not sent".
10. Links show only for pending invites, to the operator and the hotel's admin.
