# Understudy

*An understudy learns your part, rehearses it, and has everything ready — but
never goes on stage in your place.*

A GTM agent for X that does the preparation work of building a presence — finding
what's worth responding to, turning rough notes into publishable drafts, staging
and scheduling — while every word that actually goes out is one you approved.

Currently X-only. See `x-req.md` for the original PRD (a few of its assumptions
have since been overtaken by API changes — noted inline below).

## Motivation

Building a presence on X takes two things that don't scale: posting consistently,
and replying to the right people. Both are mostly *preparation* — finding the
conversation, getting from a half-formed thought to something publishable. The
writing itself is the small part.

The obvious fix is to point an LLM at it, and that fails in two specific ways:

**Generic output gets ignored.** A model writing "a good tweet about X" produces
something that sounds like everyone else. On a platform where voice *is* the
differentiator, that's worse than posting nothing. So this system never writes
from a blank slate — every draft is conditioned on a corpus of posts you actually
published, and once metrics exist, weighted toward the ones that actually landed.

**Automated engagement gets you suspended.** Auto-liking and auto-replying is the
single clearest pattern platforms act on. So Understudy will fetch, rank, draft,
and stage — but it never likes, never replies, and never publishes anything you
haven't explicitly moved to `Ready to post`.

What's left is the honest division of labour: the machine does the fetching,
deduping, ranking, and first-draft writing; you do the judging and the sending.
Every automated step ends at a review gate in Notion, not at the API.

A third principle emerged while building, after a few self-inflicted bugs:
**schema lives in code, not in prose.** When the database schema was described in
both skill instructions and Python, the two drifted and things broke silently.
Now `TWEET_DRAFTS_SCHEMA` is the single definition and the skills only describe
how to *use* the fields.

## What this does

Two independent pipelines that share a voice corpus. Neither one automates
engagement on your behalf — you always stay in the loop at the review step.

```
ENGAGEMENT — find other people's posts worth replying to
─────────────────────────────────────────────────────────────────────────────
  discover_accounts.py ──▶ Discovery Database ──▶ you mark Approved
  (search topics for                                     │
   accounts worth tracking)              --promote ──────┘
                                              │
                                              ▼
                                        interests.md
                                       (accounts + topics)
                                              │
                        ┌─────────────────────┴───────────┐
                        ▼                                 ▼
                  discover.py                      check_mentions.py
              (posts by topic/account)          (replies + @-mentions)
                        │                                 │
                        └────────────┬────────────────────┘
                                     ▼
                            Response Calendar
                          Status=New, Source=…
                                     │
                                     ▼
                            curate-discoveries
                       prunes using your `status` signal
                                     │
                                     ▼
                             draft-replies ──reads──▶ voice_corpus.json
                        writes Reply 1 / 2 / 3                ▲
                                     │                        │
                                     ▼                        │
                        YOU pick one (`Selected`)             │
                        and reply by hand on X                │
                                     │                        │
                                     ▼                        │
                     you mark `status` + `Posted`             │
                          │                                   │
                          ├──▶ trains next curation run       │
                          └──▶ sync_replies.py ───────────────┘


PUBLISHING — turn rough notes into posts
─────────────────────────────────────────────────────────────────────────────
  your rough notes
  (Notion page body)
        │
        ▼
  Stage = Ready for AI Review
        │
        ▼
  polish-tweet skill ──reads──▶ voice_corpus.json
        │                              ▲
        ▼                              │
  Final Text written                   │ appended on every
  Stage = Ready for Human Review       │ successful post
        │                              │
        ▼                              │
  YOU review in Notion                 │
        │                              │
        ├── reject → Stage = Rejected Agent Post ──┐
        │            (retry via skill, reads       │
        │             your Notion comments) ───────┘
        │
        └── approve → Stage = Ready to post
                      + set Scheduled Time
                             │
                             ▼
                    post_ready.py / post_all_due.py
                    (only fires when Scheduled Time has passed)
                             │
                             ▼
                    Stage = Posted ──────────────▶ voice_corpus.json
                                                          ▲
                                        fetch_metrics.py ─┘
                                        (impressions, engagement rate
                                         → polish prefers what landed)
```

**Why some parts are scripts and others are skills.** Anything that spends money,
must be deterministic, or runs unattended is a script — fetching, deduping,
ranking, posting. Anything needing judgment is a skill — voice matching, relevance
curation. The Notion schema also lives in code (`TWEET_DRAFTS_SCHEMA`) rather than
in skill prose, because when it lived in both they drifted and broke.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env
```

Fill in `.env`:

| Variable | Needed for | How to get it |
|---|---|---|
| `X_BEARER_TOKEN` | all reads | X developer portal, app-only bearer. Needs pay-per-use credits loaded. |
| `X_CLIENT_ID` / `X_CLIENT_SECRET` | posting | Same app → User authentication settings → Read+Write, Confidential client, callback `http://127.0.0.1:8765/callback` |
| `NOTION_API_TOKEN` | all Notion access | notion.so/my-integrations, then share your Notion page with the integration |
| `NOTION_TWEET_DRAFTS_DB_ID` | publishing | Written automatically by `setup.py` |
| `NOTION_RESPONSE_CALENDAR_DB_ID` | engagement | The Response Calendar database id |
| `NOTION_DISCOVERY_DB_ID` | account discovery | The Discovery Database id |

The `NOTION_API_TOKEN` is **separate from Claude Code's Notion connection** — that
one only exists inside a live chat session, and the posting scripts run unattended.

### First run, in order

```bash
.venv/bin/python scripts/smoke_test.py <username>                    # 1. auth works?
.venv/bin/python scripts/setup.py <notion-page-url> <your-username>  # 2. bootstrap
.venv/bin/python scripts/x_oauth_login.py                            # 3. authorize posting
```

**`setup.py`** creates the `Tweet Drafts` database under that Notion page with the
full schema, writes its id into `.env`, and seeds `voice_corpus.json` from your
recent posts (up to 30 short → `tweets`, up to 10 long → `articles`). It refuses to
run twice unless you pass `--force-new-db`.

**`x_oauth_login.py`** opens your browser, catches the redirect on `127.0.0.1:8765`,
and saves a refreshable token to `x_oauth_token.json` (gitignored). Re-run it if
that file is deleted or the refresh token is revoked.

---

## Pipeline 1 — Engagement

### Configure what to watch

`interests.md` — plain markdown, `## Accounts` and `## Topics` sections. Only `-`
bullets are parsed, so prose and notes anywhere in the file are ignored.

You can populate the Accounts section by hand, or let the system suggest people:

```bash
.venv/bin/python scripts/discover_accounts.py             # stage candidates
.venv/bin/python scripts/discover_accounts.py --promote   # Approved → interests.md
```

Searches your topics, collects the authors, filters out accounts under
`--min-followers` (default 500), and stages them in the **Discovery Database** with
`Review Status = New`. You mark the good ones `Approved` in Notion, then `--promote`
appends them to `interests.md`. The review gate is deliberate — an account only
starts costing read budget in `discover.py` once you've okayed it.

### Discover

```bash
.venv/bin/python scripts/discover.py              # stages into Response Calendar
.venv/bin/python scripts/discover.py --dry-run    # preview, writes nothing
.venv/bin/python scripts/harvest_and_rank.py      # older: prints only, accounts only
```

Fetches from accounts and topics, ranks by engagement, dedupes against both a local
seen-set (`gtm_agent.db`) and rows already in the Response Calendar, then writes the
top `--limit` (default 15) as `Status = New`. Read-only against X — it never likes,
replies, or posts.

### Mentions

```bash
.venv/bin/python scripts/check_mentions.py <your-username>
```

Replies to your posts, @-mentions and quotes are otherwise invisible to the system.
These land in the **same** Response Calendar, so curation and reply-drafting work on
them unchanged — the `Source` property (`discovery` vs `mention`) tells them apart,
and mentions are usually worth answering first.

### Curate

The `curate-discoveries` skill runs the script, then prunes what it staged by
learning from what you've engaged with before.

**The Response Calendar has two status properties differing only by case.** Notion
matches property names exactly, so confusing them fails silently:

| Property | Values | Written by |
|---|---|---|
| `Status` | `New`, `Reviewed`, `Stale`, `Rejected (irrelevant)`, `Rejected (IDK what to say)` | the pipeline |
| `status` | `Commented`, `Rejected`, `not-commented` | **you only** |

The lowercase `status` is the learning signal: `Commented` = positive, `Rejected` =
negative, `not-commented` = **neutral** (no reply happened, but the content wasn't
necessarily bad). The skill reads it and writes only capital `Status` — writing the
lowercase one would corrupt the very signal it learns from.

### Draft replies

The **`draft-replies`** skill fills `Reply 1`, `Reply 2`, `Reply 3` on staged rows
with three genuinely different angles, in your voice — read from the same
`voice_corpus.json` the publishing flow uses. That's the link between the two
pipelines: discovery finds the post, the corpus supplies the voice.

You then set `Selected` to the one you want and **reply by hand on X**. Nothing
here posts for you — automated engagement is what gets accounts suspended
(`x-req.md` §2.5), so the API is never used to reply.

The skill only ever writes the three `Reply` fields. `Selected`, `Approved`,
`Posted`, `Self-Written Reply` and the lowercase `status` all record what *you*
decided — it never touches them.

Once you've replied, tick `Posted` and set `Selected`, then:

```bash
.venv/bin/python scripts/sync_replies.py
```

That copies the reply you actually sent into `voice_corpus.json` as
`post_type: "reply"`, so future reply drafts learn from your real replies rather
than only from your original posts. `Selected = Like/RT` is skipped — no text to
learn from. Replies are keyed by Notion page id (there's no tweet id, since you
posted by hand), so re-running is safe.

### Two API caveats

**Impressions work, but weakly.** `public_metrics.impression_count` is included in
ranking at a deliberately tiny weight (0.01) — impressions run orders of magnitude
larger than likes and would otherwise swamp real engagement, and for other people's
posts the field is frequently `0`. Nothing depends on it. *This supersedes `x-req.md`
§2.1, which says impressions aren't available for others' posts.*

**Topics are wired up but unproven.** Recent-search covers the last 7 days only, and
whether it's callable on pay-per-use is `x-req.md` open item 2. `discover.py` degrades
per-source — a failing topic is reported and accounts still work.

---

## Pipeline 2 — Publishing

### Draft

Put your rough notes in the **page body** of a `Tweet Drafts` row and set
`Stage = Ready for AI Review`. Set `post-type` to `single-thread`, `multi-thread`,
or `article`.

The **`polish-tweet`** skill rewrites it in your voice, writes the result to
`Final Text`, and sets `Stage = Ready for Human Review`. No chat approval gate —
review happens in Notion, not in conversation.

| `post-type` | What it produces | Format in `Final Text` |
|---|---|---|
| `single-thread` | one tweet | plain text, ≤280 chars |
| `multi-thread` | reply-chained thread | segments separated by a line of `---`, each ≤280 |
| `article` | long-form Article | body only; headline goes in the `Title` property |

### Review

In Notion, pick one:
- **`Stage = Ready to post`** + set `Scheduled Time` → queued for publishing
- **Edit `Final Text`** directly → then approve
- **`Stage = Rejected Agent Post`** → the skill can retry it, and will read your
  Notion **comments** on the row as feedback for what to change

### Post

```bash
.venv/bin/python scripts/post_ready.py      # one due row per run
.venv/bin/python scripts/post_all_due.py    # every due row, oldest first
```

Or ask Claude to "post my ready tweets" — the `post-ready-tweets` skill is a thin
trigger around `post_all_due.py`.

Both only fire on rows where `Stage = Ready to post` **and** `Scheduled Time` is in
the past. A row with no `Scheduled Time`, or one still in the future, is never
touched — nothing is auto-scheduled or auto-spaced, so pacing is entirely yours.

On success: `Stage = Posted`, and the post is appended to `voice_corpus.json`. On
failure: the error goes to `Post Error` and `Stage` is left alone so it retries.

**No cron.** Run it by hand. Do that a few times before considering any automation —
it spends real money per post and posting can't be undone.

### Two failure cases that need you, not a re-run

Both leave real state on X and deliberately do **not** auto-retry:

- **Thread fails partway** → earlier tweets are live on X. The error records their
  IDs. Retrying would duplicate the successful prefix.
- **Article draft created but publish failed** → the draft exists on X. The error
  records the draft id. Retrying would create a second draft.

---

## The voice corpus

`voice_corpus.json` (gitignored) is the **only** source of style exemplars for
`polish-tweet`:

```json
{
  "tweets":   [{"id", "text", "posted_url", "post_type"}],
  "articles": [{"id", "title", "text", "posted_url"}]
}
```

Two buckets so short-form and long-form voice don't bleed into each other. It's
seeded once by `setup.py` (or `fetch_voice_corpus.py`), then grows automatically —
`post_ready.py` / `post_all_due.py` append on every successful post. That's the only
append point, tied to a real post actually happening. `polish-tweet` only reads it.

**X Articles cannot be read through the API at all** — the tweet announcing an
Article contains only a t.co link, and `note_tweet` returns long-*post* text, never
Article content. So the `articles` bucket is seeded from long posts (>280 chars),
the closest available long-form voice, and only fills properly as you publish
articles through this pipeline.

`sync_replies.py` adds replies you actually sent (from the Response Calendar) as
`post_type: "reply"` entries — the closest exemplars for drafting new replies.

`sync_posted.py` is separate and optional: it imports your X history into
`Tweet Drafts` as `Posted` rows for visibility in the Notion UI. It does **not**
feed `polish-tweet`.

### Performance feedback

```bash
.venv/bin/python scripts/fetch_metrics.py
```

Pulls impressions, profile clicks and engagement counts for your own posts and
attaches them to their corpus entries as a `metrics` object with an
`engagement_rate`. `polish-tweet` and `draft-replies` then prefer exemplars that
actually landed, instead of treating every past post as equally good.

Two things to know:
- **Private metrics only cover the last 30 days.** Older posts come back with
  public metrics only. Run this regularly if you want history to accumulate.
- **Missing metrics mean unmeasured, not bad.** Both skills are explicitly told
  never to treat an absent `metrics` object as a negative signal — otherwise a
  brand-new corpus would look like a corpus full of failures.

---

## Layout

**Config you edit**
- `interests.md` — accounts + topics to discover from
- `.env` — credentials

**Generated (all gitignored)**
- `voice_corpus.json` — style exemplars
- `gtm_agent.db` — seen-set + user-id cache
- `x_oauth_token.json` — posting token

**Library** (`src/gtm_agent/`)
- `config.py` — env var loading
- `x_client.py` — X API: reads, tweets, threads, Articles, OAuth-authed writes
- `x_oauth.py` — OAuth 2.0 PKCE login + token refresh
- `notion_client.py` — Notion API; holds `TWEET_DRAFTS_SCHEMA`, the canonical schema
- `interests.py` — parses `interests.md`
- `store.py` — SQLite seen-set + user-id cache
- `ranking.py` — engagement scoring, optional recency decay
- `harvest.py` — account fetch + dedupe + rank
- `posting.py` — thread/article parsing, validation, `post_row()`
- `voice_corpus.py` — corpus load/save, `append_tweet` / `append_article`

**Scripts**
- `setup.py` — one-time bootstrap (creates DB, seeds corpus)
- `smoke_test.py` — one-call auth check
- `x_oauth_login.py` — one-time posting authorization
- `discover.py` — fetch + rank + stage posts into Response Calendar
- `discover_accounts.py` — find accounts by topic; `--promote` moves Approved ones into `interests.md`
- `check_mentions.py` — stage replies/@-mentions into Response Calendar
- `harvest_and_rank.py` — older print-only, accounts-only variant
- `post_ready.py` / `post_all_due.py` — publish due rows
- `fetch_voice_corpus.py` — seed/merge corpus from your timeline
- `fetch_metrics.py` — attach your own post analytics to corpus entries
- `sync_replies.py` — add replies you sent to the corpus as `post_type: reply`
- `sync_posted.py` — import X history into Notion for visibility

**Skills** (`.claude/skills/`)
- `polish-tweet` — rough note → voice-matched draft
- `curate-discoveries` — run discovery, prune by past `status` signal
- `draft-replies` — write Reply 1/2/3 options in your voice (you post them by hand)
- `post-ready-tweets` — thin trigger for `post_all_due.py`

---

## Status

**Nothing has run against the live X or Notion APIs yet.** Every path is verified
offline with mocked calls; all of it is blocked on credentials + X credits.

Working, pending live verification:
- Discovery (accounts + topics), ranking, dedupe, staging to Response Calendar
- Polish for all three post types, plus rejected-draft retry using Notion comments
- Reply drafting into the Response Calendar, sharing the publishing flow's voice corpus
- Posting for all three post types, including reply-chained threads and the
  Articles API, with both partial-failure paths handled
- Voice corpus seeding and automatic growth on post
- Performance metrics feeding exemplar selection; sent replies feeding the corpus
- Mention monitoring and account discovery, both staged for manual review

Known gaps:
- **Topics unverified** — recent-search may not be callable on pay-per-use
  (`x-req.md` open item 2). Degrades gracefully if not.
- **No automatic polling** — `polish-tweet` must be asked; it doesn't watch for
  `Ready for AI Review` rows on its own.
- **No scheduler** — posting is manual, gated on `Scheduled Time`.
- **`sync_posted.py` dedupes by exact text match**, not tweet ID, because the
  `Posted URL` property was removed from the database. Weaker, but avoids
  re-importing everything on every run.
- **Articles need X Premium**, and a thin `articles` corpus means thin long-form
  voice matching until you've published a few.

---

## Future work

Roughly in order of how much they'd change day-to-day use.

### Close the loops that are still open by hand

- **Automatic polling.** `polish-tweet` has to be asked. A watcher that picks up
  `Ready for AI Review` rows on its own would make the publishing pipeline
  self-feeding — you'd drop a rough note in Notion and find a draft waiting.
- **Scheduling.** Posting is manual and gated on `Scheduled Time`. The cron and
  auto-spacing logic were deliberately removed once, so any return should be
  opt-in and still respect the one-post-per-run safety cap.
- **Best time to post.** Once `fetch_metrics.py` has accumulated a few months of
  history, engagement rate by hour-of-day becomes answerable from your own data
  rather than from generic advice. Blocked on history, not on code.

### Make the feedback loop sharper

- **Reply performance.** Replies you send are now voice exemplars, but nothing
  measures whether they landed. Replies are your own tweets, so their metrics are
  fetchable — it needs the reply's tweet id, which means either capturing it when
  you reply or matching text back to your timeline.
- **What actually distinguishes a winner.** With enough metrics history, the
  interesting question stops being "which posts did well" and becomes "what do
  the winners have in common" — length, hook shape, time, topic, thread vs single.
  That analysis would sharpen `polish-tweet` far more than more exemplars would.
- **Thread vs single-post comparison.** The corpus tags `post_type`, and metrics
  are per-post, so this is mostly a reporting question waiting on data.

### Extend the graph

- **LinkedIn** (`linkedin-req.md` exists but is empty). The shape should port
  cleanly — discovery, voice corpus, review gates — but LinkedIn's API is far more
  restrictive about posting and reading, so that needs verifying before designing.
  Worth reusing the corpus concept while keeping voice *separate*: LinkedIn voice
  and X voice are legitimately different registers.
- **Cross-post adaptation.** Once a second platform exists: take one idea and
  render it correctly for each, rather than copy-pasting the same text.

### Deferred in the original PRD, still deferred

- **Context graph** of who you've talked to and about what, so replies can
  reference history. `x-req.md` cut this deliberately; it only becomes worthwhile
  once the reply volume is high enough that you stop remembering context yourself.
- **DM handling.** Cut by choice, and reasonable to keep cut — DMs are higher
  stakes and lower volume than replies.

### Explicitly not planned

- **Auto-liking, auto-replying, or posting without approval.** This is the one
  design rule the whole system is built around, not a limitation to remove later.
  Anything that removes the review gate makes the tool actively dangerous to the
  account it's meant to grow.
- **Vanity dashboards.** Follower charts are cheap to build and tell you nothing
  you can act on. Engagement rate on specific posts already answers the useful
  version of that question.
