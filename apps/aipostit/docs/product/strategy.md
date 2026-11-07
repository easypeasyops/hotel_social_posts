# Strategy

## Who it is for

Hotels in Türkiye that want a steady social presence without a marketing team: a hotel admin
or owner who has photos and no time. Their guests are largely foreign (assumed: German,
Russian, British and domestic in varying mixes; not yet confirmed with any hotel).

## What it does today

aipostit 0.4.x, live in prod: hotels upload photos; Claude drafts Turkish posts every week;
hotel staff or an operator review them as network previews (Instagram, Facebook, TikTok,
Google Business Profile), edit, approve or reject; approved posts go to Buffer and their
outcome syncs back hourly. Growth and premium tiers also get DeepL translations, which are
not published anywhere yet. The company is Cem Consulting (consultingcem.com).

Tiers in the code (`app/hotels/models.py`), not yet tested with a buyer: standard $299/mo
(TR + EN), growth $599/mo (TR + EN, DE, RU, AR), premium $899/mo (growth + priority).

## Stage and constraints

- **Pre-revenue** (2026-11-06): the product works end to end, no hotel pays for it yet. The
  first job is finding the first hotels and learning what they would pay for, not adding
  features.
- **One engineer** (Emrah) builds, operates and sells it. Every idea is weighed against his
  time: the cheapest test of an idea comes before building it, and a "not now" is a decision
  worth writing down.
- No customer data, analytics or interviews yet: rankings are judgement until hotels confirm.

## Where we can win

Social platforms optimise their own feed. They don't know the hotel's business (empty dates,
guest markets, reviews, bookings), and each one sees only itself. aipostit is worth paying
for where it uses that knowledge, not where it repeats what a platform gives away for free
(viewer-side caption translation, for example: see decisions.md).

## How we decide

1. Does it make a hotel money or save it real time? Bookings beat likes.
2. Can we test it without code, or with one small PR?
3. Does it build on what aipostit already holds (photos, drafts, reviews, staff)?
4. What does it cost Emrah to build and to run?
