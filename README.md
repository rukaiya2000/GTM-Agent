<p align="center">
  <img src="assets/logo.svg" alt="Wingman" width="440">
</p>

<p align="center">
  <strong>A go-to-market agent for X that finds the conversations worth joining and drafts what to say, while you decide what actually goes out.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/status-work%20in%20progress-F59E0B?style=flat-square" alt="Status: work in progress">
  <img src="https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/platform-X-1D9BF0?style=flat-square" alt="Platform: X">
  <img src="https://img.shields.io/badge/storage-Notion-000000?style=flat-square" alt="Storage: Notion">
</p>

---

> **Status: ongoing project, under active development.**
> The full pipeline is implemented and verified offline against mocked API calls,
> but no path has yet been exercised against the live X or Notion APIs. Interfaces,
> schemas, and skill definitions are still subject to change. See
> [Project status](#project-status) for exactly what is and is not proven.

*A wingman goes into the room ahead of you, works out who is worth talking to, and
opens the conversation. You are still the one who shows up and speaks.*

Currently X only. LinkedIn support is planned (see [Roadmap](#roadmap)). The
original product requirements live in `x-req.md`; several of its API assumptions
have since been overtaken by platform changes, which are noted inline below.

## Contents

- [Motivation](#motivation)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Pipeline 1: Engagement](#pipeline-1-engagement)
- [Pipeline 2: Publishing](#pipeline-2-publishing)
- [The voice corpus](#the-voice-corpus)
- [Project layout](#project-layout)
- [Project status](#project-status)
- [Roadmap](#roadmap)

## Motivation

Building a presence on X requires two things that do not scale: posting
consistently, and replying to the right people. Both are mostly preparation work.
Finding the conversation worth joining, and getting from a half formed thought to
something publishable, is where the time goes. The writing itself is the small
part.

The obvious solution is to point a language model at the problem. That fails in
two specific ways, and both shaped this design.

**Generic output gets ignored.** A model asked to write "a good tweet about X"
produces something that sounds like everyone else. On a platform where voice is
the differentiator, that is worse than posting nothing. Wingman therefore never
writes from a blank slate. Every draft is conditioned on a corpus of posts you
actually published, and once performance data exists, weighted toward the ones
that measurably landed.

**Automated engagement gets accounts suspended.** Auto-liking and auto-replying is
the clearest pattern platforms act on. Wingman will fetch, rank, draft, and
stage, but it never likes, never replies, and never publishes anything you have
not explicitly moved to `Ready to post`.

What remains is a clear division of labour. The system handles fetching,
deduplication, ranking, and first-draft writing. You handle judgement and
publication. Every automated step terminates at a review gate in Notion rather
than at an API call.

A third principle emerged during development, after several self inflicted bugs:
**schema belongs in code, not in prose.** When the database schema was described
both in skill instructions and in Python, the two definitions drifted and broke
silently. `TWEET_DRAFTS_SCHEMA` is now the single definition, and the skills only
describe how to use those fields.

## Architecture

Two independent pipelines share a common voice corpus. Neither automates
engagement on your behalf; you remain in the loop at every review step.

### Engagement pipeline

Finds other people's posts worth replying to.

```
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
```

### Publishing pipeline

Turns rough notes into posts.

```
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

### Scripts versus skills

The split is deliberate. Anything that spends money, must be deterministic, or
runs unattended is a Python script: fetching, deduplication, ranking, posting.
Anything requiring judgement is a Claude Code skill: voice matching, relevance
curation, reply drafting.

## Prerequisites

- Python 3.11 or later
- An X developer account with pay-per-use billing and credits loaded
- X Premium, if you intend to publish long-form Articles
- A Notion workspace, with an internal integration you can create
- Claude Code, for the skill-based steps

## Installation

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env
```

## Configuration

Populate `.env` with the following:

| Variable | Required for | How to obtain |
|---|---|---|
| `X_BEARER_TOKEN` | all read operations | X developer portal, app-only bearer token. Requires pay-per-use credits. |
| `X_CLIENT_ID`, `X_CLIENT_SECRET` | publishing | Same app, under User authentication settings. Read and write, confidential client, callback `http://127.0.0.1:8765/callback` |
| `NOTION_API_TOKEN` | all Notion access | notion.so/my-integrations, then share the target page with the integration |
| `NOTION_TWEET_DRAFTS_DB_ID` | publishing | Written automatically by `setup.py` |
| `NOTION_RESPONSE_CALENDAR_DB_ID` | engagement | The Response Calendar database ID |
| `NOTION_DISCOVERY_DB_ID` | account discovery | The Discovery Database ID |

`NOTION_API_TOKEN` is distinct from Claude Code's own Notion connection. The
latter exists only inside a live chat session, whereas the posting scripts run
unattended and require their own credential.

### Initial setup

Run once, in this order:

```bash
.venv/bin/python scripts/smoke_test.py <username>                    # 1. verify auth
.venv/bin/python scripts/setup.py <notion-page-url> <your-username>  # 2. bootstrap
.venv/bin/python scripts/x_oauth_login.py                            # 3. authorize posting
```

`setup.py` creates the `Tweet Drafts` database under the given Notion page with
the full schema, writes its ID into `.env`, and seeds `voice_corpus.json` from
your recent posts (up to 30 short-form entries and 10 long-form). It refuses to
run a second time unless invoked with `--force-new-db`.

`x_oauth_login.py` opens a browser for authorization, captures the redirect on
`127.0.0.1:8765`, and stores a refreshable token in `x_oauth_token.json` (which is
gitignored). Re-run it if that file is deleted or the refresh token is revoked.

## Pipeline 1: Engagement

### Configuring sources

`interests.md` is plain markdown containing `## Accounts` and `## Topics`
sections. Only `-` bullets are parsed, so prose and notes may appear anywhere in
the file without affecting behaviour.

You can populate the Accounts section manually, or have the system propose
candidates:

```bash
.venv/bin/python scripts/discover_accounts.py             # stage candidates
.venv/bin/python scripts/discover_accounts.py --promote   # Approved to interests.md
```

The first form searches your topics, collects post authors, filters out accounts
below `--min-followers` (default 500), and stages them in the Discovery Database
with `Review Status = New`. After you mark the useful ones `Approved` in Notion,
`--promote` appends them to `interests.md`. The manual review gate is intentional:
an account only begins consuming read budget in `discover.py` once you have
approved it.

### Discovering posts

```bash
.venv/bin/python scripts/discover.py              # stage into Response Calendar
.venv/bin/python scripts/discover.py --dry-run    # preview without writing
.venv/bin/python scripts/harvest_and_rank.py      # legacy: prints only, accounts only
```

Fetches from configured accounts and topics, ranks by engagement, deduplicates
against both a local seen-set (`gtm_agent.db`) and rows already present in the
Response Calendar, then writes the top `--limit` results (default 15) with
`Status = New`. All operations against X are read-only; the script never likes,
replies, or posts.

### Monitoring mentions

```bash
.venv/bin/python scripts/check_mentions.py <your-username>
```

Replies to your posts, @-mentions, and quotes are otherwise invisible to the
system. These are staged into the same Response Calendar, so curation and reply
drafting operate on them unchanged. The `Source` property distinguishes
`discovery` from `mention`; mentions generally warrant a faster response.

### Curating

The `curate-discoveries` skill runs the discovery script, then prunes the staged
results based on what you have engaged with previously.

**Important:** the Response Calendar contains two status properties whose names
differ only by capitalization. Notion matches property names exactly, so
confusing the two fails silently.

| Property | Values | Written by |
|---|---|---|
| `Status` | `New`, `Reviewed`, `Stale`, `Rejected (irrelevant)`, `Rejected (IDK what to say)` | the pipeline |
| `status` | `Commented`, `Rejected`, `not-commented` | you only |

The lowercase `status` is the learning signal. `Commented` is positive evidence,
`Rejected` is negative, and `not-commented` is explicitly neutral: no reply
occurred, but the content was not necessarily unsuitable. The skill reads this
property and writes only the capitalized `Status`. Writing the lowercase property
would corrupt the signal the skill depends on.

### Drafting replies

The `draft-replies` skill populates `Reply 1`, `Reply 2`, and `Reply 3` on staged
rows with three substantively different angles, written in your voice from the
same `voice_corpus.json` used by the publishing pipeline. This is the connection
between the two pipelines: discovery locates the post, and the corpus supplies
the voice.

You then set `Selected` to your preferred option and reply manually on X. Nothing
in this system posts on your behalf. Automated engagement is the primary cause of
account suspensions (`x-req.md` §2.5), so the API is never used to reply.

The skill writes only the three `Reply` fields. `Selected`, `Approved`, `Posted`,
`Self-Written Reply`, and the lowercase `status` all record your decisions, and
are never modified.

Once you have replied, set `Selected` and tick `Posted`, then run:

```bash
.venv/bin/python scripts/sync_replies.py
```

This copies the reply you actually sent into `voice_corpus.json` with
`post_type: "reply"`, so future reply drafts learn from your real replies rather
than only from your original posts. Rows with `Selected = Like/RT` are skipped, as
there is no text to learn from. Replies are keyed by Notion page ID rather than
tweet ID (since you posted manually), so the script is safe to re-run.

### API constraints

**Impressions are available but unreliable.** `public_metrics.impression_count`
contributes to ranking at a deliberately small weight (0.01). Impression counts
run orders of magnitude larger than like counts and would otherwise dominate the
score, and for other users' posts the field frequently returns `0`. No behaviour
depends on its presence. This supersedes `x-req.md` §2.1, which states that
impressions are unavailable for other users' posts.

**Topic search is implemented but unverified.** Recent-search covers only the
past seven days, and whether it is callable on pay-per-use billing remains
`x-req.md` open item 2. `discover.py` degrades per source: a failing topic is
reported individually and account-based discovery continues to work.

## Pipeline 2: Publishing

### Drafting

Place your rough notes in the page body of a `Tweet Drafts` row, set
`Stage = Ready for AI Review`, and set `post-type` to `single-thread`,
`multi-thread`, or `article`.

The `polish-tweet` skill rewrites the note in your voice, writes the result to
`Final Text`, and sets `Stage = Ready for Human Review`. There is no chat approval
step; review takes place in Notion.

| `post-type` | Output | Format in `Final Text` |
|---|---|---|
| `single-thread` | one post | plain text, 280 characters maximum |
| `multi-thread` | reply-chained thread | segments separated by a line containing only `---`, each within 280 characters |
| `article` | long-form Article | body only; the headline is taken from the `Title` property |

### Reviewing

In Notion, choose one of the following:

- Set `Stage = Ready to post` and populate `Scheduled Time` to queue for
  publication.
- Edit `Final Text` directly, then approve.
- Set `Stage = Rejected Agent Post`. The skill can then retry the draft, reading
  any Notion comments on the row as feedback.

### Publishing

```bash
.venv/bin/python scripts/post_ready.py      # one due row per run
.venv/bin/python scripts/post_all_due.py    # all due rows, oldest first
```

Alternatively, ask Claude to post your ready tweets; the `post-ready-tweets` skill
is a thin wrapper around `post_all_due.py`.

Both scripts act only on rows where `Stage = Ready to post` and `Scheduled Time`
lies in the past. Rows without a `Scheduled Time`, or with one still in the
future, are never touched. Nothing is auto-scheduled or auto-spaced, so posting
cadence remains entirely under your control.

On success, `Stage` is set to `Posted` and the post is appended to
`voice_corpus.json`. On failure, the error is written to `Post Error` and `Stage`
is left unchanged so the row is retried on the next run.

There is no cron integration by design. Run these scripts manually, and do so
several times before considering any automation: each post costs money and cannot
be undone.

### Partial failure cases

Two failure modes leave real state on X and deliberately do not auto-retry, as a
retry would compound the problem rather than resolve it. Both require manual
intervention.

- **A thread failing partway through.** Earlier posts in the thread are already
  live. The error message records their IDs. Retrying would duplicate the
  successfully posted prefix.
- **An Article draft created but not published.** The draft exists on X. The error
  message records the draft ID. Retrying would create a second draft.

## The voice corpus

`voice_corpus.json` (gitignored) is the sole source of style exemplars for
`polish-tweet` and `draft-replies`:

```json
{
  "tweets":   [{"id", "text", "posted_url", "post_type", "metrics"}],
  "articles": [{"id", "title", "text", "posted_url", "metrics"}]
}
```

The two buckets keep short-form and long-form voice separate. The file is seeded
once by `setup.py` (or `fetch_voice_corpus.py`) and grows automatically
thereafter: `post_ready.py` and `post_all_due.py` append on every successful
post. That is the only automatic append point, and it is tied to a post actually
being published.

**X Articles cannot be read through the API.** The post announcing an Article
contains only a t.co link, and `note_tweet` returns long-*post* text rather than
Article content. The `articles` bucket is therefore seeded from long posts
(over 280 characters), which is the closest available long-form voice reference,
and fills properly only as you publish Articles through this pipeline.

`sync_replies.py` adds replies you actually sent as `post_type: "reply"` entries,
which are the closest available exemplars when drafting new replies.

`sync_posted.py` is separate and optional. It imports your X history into
`Tweet Drafts` as `Posted` rows for visibility within the Notion interface, and
does not feed the voice corpus.

### Performance feedback

```bash
.venv/bin/python scripts/fetch_metrics.py
```

Retrieves impressions, profile clicks, and engagement counts for your own posts,
attaching them to the corresponding corpus entries as a `metrics` object
containing an `engagement_rate`. Both skills then favour exemplars that
demonstrably performed, rather than treating every past post as equally
representative.

Two constraints apply:

- **Private metrics cover only the last 30 days.** Older posts return public
  metrics only. Run this regularly for history to accumulate.
- **Absent metrics indicate "unmeasured", not "unsuccessful".** Both skills are
  explicitly instructed never to treat a missing `metrics` object as negative
  evidence, since a newly seeded corpus would otherwise appear to be a corpus of
  failures.

## Project layout

**User-editable configuration**

- `interests.md`: accounts and topics to discover from
- `.env`: credentials

**Generated files (all gitignored)**

- `voice_corpus.json`: style exemplars
- `gtm_agent.db`: seen-set and user ID cache
- `x_oauth_token.json`: publishing token

**Library** (`src/gtm_agent/`)

| Module | Responsibility |
|---|---|
| `config.py` | Environment variable loading |
| `x_client.py` | X API: reads, posts, threads, Articles, metrics |
| `x_oauth.py` | OAuth 2.0 PKCE login and token refresh |
| `notion_client.py` | Notion API; owns `TWEET_DRAFTS_SCHEMA` |
| `interests.py` | Parses `interests.md` |
| `store.py` | SQLite seen-set and user ID cache |
| `ranking.py` | Engagement scoring with optional recency decay |
| `harvest.py` | Account fetch, deduplication, ranking |
| `posting.py` | Thread and Article parsing, validation, `post_row()` |
| `voice_corpus.py` | Corpus load, save, append, and metric attachment |

**Scripts** (`scripts/`)

| Script | Purpose |
|---|---|
| `setup.py` | One-time bootstrap: creates the database, seeds the corpus |
| `smoke_test.py` | Single-call authentication check |
| `x_oauth_login.py` | One-time publishing authorization |
| `discover.py` | Fetch, rank, and stage posts into the Response Calendar |
| `discover_accounts.py` | Find accounts by topic; `--promote` adds approved ones to `interests.md` |
| `check_mentions.py` | Stage replies and mentions into the Response Calendar |
| `harvest_and_rank.py` | Legacy print-only, accounts-only variant |
| `post_ready.py`, `post_all_due.py` | Publish due rows |
| `fetch_voice_corpus.py` | Seed or merge corpus entries from your timeline |
| `fetch_metrics.py` | Attach post analytics to corpus entries |
| `sync_replies.py` | Add sent replies to the corpus |
| `sync_posted.py` | Import X history into Notion for visibility |

**Skills** (`.claude/skills/`)

| Skill | Purpose |
|---|---|
| `polish-tweet` | Rough note to voice-matched draft |
| `curate-discoveries` | Run discovery, prune using the `status` signal |
| `draft-replies` | Write three reply options in your voice |
| `post-ready-tweets` | Thin trigger for `post_all_due.py` |

## Project status

**No component has yet been run against the live X or Notion APIs.** Every code
path is verified offline against mocked calls. Live verification is blocked on
credentials and X API credits.

Implemented and offline-verified:

- Discovery across accounts and topics, with ranking, deduplication, and staging
- Account discovery and mention monitoring, both staged for manual review
- Voice-matched drafting for all three post types, plus rejected-draft retry
  informed by Notion comments
- Reply drafting sharing the publishing pipeline's voice corpus
- Publishing for all three post types, including reply-chained threads and the
  Articles API, with both partial-failure paths handled
- Corpus seeding, automatic growth on publication, performance metric attachment,
  and sent-reply ingestion

Known limitations:

| Limitation | Detail |
|---|---|
| Topic search unverified | Recent-search may not be callable on pay-per-use billing (`x-req.md` open item 2). Degrades gracefully. |
| No automatic polling | `polish-tweet` must be invoked; it does not watch for `Ready for AI Review` rows. |
| No scheduler | Publishing is manual, gated on `Scheduled Time`. |
| Weak `sync_posted.py` deduplication | Matches on exact text rather than tweet ID, since the `Posted URL` property was removed. Avoids re-importing on every run. |
| Articles require X Premium | A sparse `articles` bucket also means weak long-form voice matching until several are published. |

## Roadmap

Ordered approximately by impact on day-to-day use.

### Closing the remaining manual loops

- **Automatic polling.** `polish-tweet` currently must be invoked explicitly. A
  watcher that picks up `Ready for AI Review` rows would make the publishing
  pipeline self-feeding: drop a rough note into Notion, return to a finished
  draft.
- **Scheduling.** Publishing is manual. Cron and auto-spacing logic were
  deliberately removed once already, so any reintroduction should be opt-in and
  must preserve the one-post-per-run safety cap.
- **Optimal posting times.** Once `fetch_metrics.py` has accumulated sufficient
  history, engagement rate by hour of day becomes answerable from your own data
  rather than from general advice. Blocked on data volume, not implementation.

### Strengthening the feedback loop

- **Reply performance.** Sent replies are now voice exemplars, but nothing
  measures their reception. Replies are your own posts, so their metrics are
  retrievable; this requires capturing the reply's tweet ID, either at reply time
  or by matching text against your timeline.
- **Characterising successful posts.** With sufficient metric history, the useful
  question shifts from which posts performed well to what the successful ones have
  in common: length, opening structure, timing, topic, thread versus single post.
  That analysis would improve drafting more than additional exemplars would.
- **Thread versus single-post comparison.** The corpus already records
  `post_type` and metrics are per-post, so this is primarily a reporting question
  awaiting data.

### Platform expansion

- **LinkedIn.** `linkedin-req.md` exists but is currently empty. The overall
  structure should port cleanly (discovery, voice corpus, review gates), but
  LinkedIn's API is considerably more restrictive regarding both reading and
  posting, so feasibility needs verification before design. The corpus concept
  should be reused while keeping voice separate: LinkedIn and X are legitimately
  different registers.
- **Cross-platform adaptation.** Once a second platform exists, render a single
  idea appropriately for each rather than duplicating identical text.

### Deferred in the original requirements

- **Context graph** of prior conversations, allowing replies to reference
  history. `x-req.md` cut this deliberately. It becomes worthwhile only once reply
  volume exceeds what you can track yourself.
- **Direct message handling.** Cut by choice, and reasonably kept cut: direct
  messages carry higher stakes at lower volume than public replies.

### Explicitly out of scope

- **Auto-liking, auto-replying, or publishing without approval.** This is the
  design constraint the entire system is built around, not a limitation to be
  removed later. Removing the review gate would make the tool actively hazardous
  to the account it exists to grow.
- **Follower-count dashboards.** Inexpensive to build and largely unactionable.
  Per-post engagement rate already answers the useful form of that question.
