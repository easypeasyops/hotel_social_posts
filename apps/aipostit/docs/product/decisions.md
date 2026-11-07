# Decisions

Newest first. Each says what was decided, why, and what would change it.

## 2026-11-06: One bet at a time: the empty-dates pilot, by hand

Of the ideas in ideas.md, "posts driven by empty dates" is the one to test first: it ties
posting to bookings, which a platform can't do. Test it with no code: the hotel description
already goes into the generation prompt (`app/generation/prompts.py`), so an operator adds
the dates, the perk and a booking link with UTM to it, generates, reviews, and asks the hotel
afterwards whether the dates filled. Build only if hotels come back with new dates
unprompted; the first build would then be a "campaign note with an end date" field.
**Changes if:** no hotel will share its empty dates, or the drafts can't be made good enough.

## 2026-11-06: Perks and packages, not discounts (proposed, to check with a hotel)

Campaign posts offer perks (spa included, late check-out), never a room price below the
OTAs': many hotels' contracts with Booking.com and Expedia forbid it (rate parity). Claude
never invents a price or an offer; it phrases only what the hotel gave.
**Changes if:** pilot hotels say parity doesn't bind them.

## 2026-11-06: Translation alone isn't the product

Instagram, Facebook and TikTok translate captions for the viewer, so "we translate your
posts" is worth little. Translation earns its keep on Google Business Profile (posts there
aren't translated), in discoverability (search and hashtags match the caption's language),
and as content written per guest market rather than translated. Direction, not yet built:
replace fixed tier languages with each hotel's target markets; one post per language on GBP,
one multi-language caption on Instagram and Facebook, never several posts per language on one
account. **Changes if:** hotels tell us their guests do read translated captions.

## 2026-11-06: Reject feedback should reach generation

Reviewers' reject feedback is stored and never read. Feeding recent rejections into the
prompt makes every hotel's drafts better each week: the next small code change after the
pilot starts.

## 2026-11-06: Release toil cut (done, PR #124)

A version bump tags itself, staging deploys itself, prod is one click: two merges per release
instead of four PRs, so Emrah's time goes to the product.
