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
- [Pipeline 3: Paper outreach](#pipeline-3-paper-outreach)
- [The voice corpus](#the-voice-corpus)
- [Founder memory](#founder-memory)
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
                          Status=New, drafts filled
                                     │
                                     ▼
                          draft-x-replies ──reads──▶ voice_corpus.json
                      prunes with your `status` signal,       ▲
                      then writes Reply 1 / 2 / 3             │
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
  polish-x-drafts skill ──reads──▶ voice_corpus.json
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
              ┌──────────────┴──────────────┐
              ▼                              ▼
    single-thread/multi-thread          article
    post_all_due.py pushes           post_all_due.py posts
    to Typefully (draft id                directly via X API,
    written back), Stage=Scheduled,       gated on Scheduled Time
    Typefully fires at Scheduled Time           │
              │                                  │
              ▼                                  │
    sync_typefully_status.py                     │
    polls Stage=Scheduled rows,                  │
    flips Stage=Posted                           │
    once Typefully publishes                     │
              │                                  │
              └──────────────┬───────────────────┘
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
Anything requiring judgement is a skill: voice matching, relevance curation,
reply drafting.

Skills live once, at `.claude/skills/`, and are runnable from either Claude
Code or Codex CLI — `.agents/skills` is a symlink to the same directory, which
is where Codex looks. There's nothing Claude-specific in the instructions
themselves; only the discovery path differs between the two tools.

## Prerequisites

- Python 3.11 or later
- An X developer account with pay-per-use billing and credits loaded
- X Premium, if you intend to publish long-form Articles
- A Typefully account with API access, if you intend to schedule single-thread/
  multi-thread posts and replies (see [Scheduled publishing via Typefully](#scheduled-publishing-via-typefully)); Articles, retweets/quote-retweets, and DMs stay on the direct X API regardless
- A Notion workspace, with an internal integration you can create
- Claude Code or Codex CLI, for the skill-based steps
- An OpenAI API key, if you intend to use the paper-outreach pipeline
- A Google Cloud OAuth client with the Gmail API enabled, if you intend to send outreach email
- The `research` extra (`uv sync --extra research`), only for the optional author-research step — it calls the Claude Agent SDK directly, so it works the same regardless of which CLI is orchestrating

## Installation

```bash
uv sync
cp .env.example .env
```

## Configuration

Populate `.env` with the following:

| Variable | Required for | How to obtain |
|---|---|---|
| `X_BEARER_TOKEN` | all read operations | X developer portal, app-only bearer token. Requires pay-per-use credits. |
| `X_CLIENT_ID`, `X_CLIENT_SECRET` | publishing, X DMs | Same app, under User authentication settings. Read and write, confidential client, callback `http://127.0.0.1:8765/callback`. DM sending additionally needs the `dm.write` scope. Still required regardless of Typefully — it covers Articles, retweets/quote-retweets, and DMs. |
| `TYPEFULLY_API_KEY` | scheduled single-thread/multi-thread posts and replies | typefully.com/settings/integrations |
| `TYPEFULLY_SOCIAL_SET_ID` | same as above | `GET /v2/social-sets` with the API key above; see [Scheduled publishing via Typefully](#scheduled-publishing-via-typefully) |
| `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET` | outreach email | Google Cloud OAuth client (Desktop app type), Gmail API enabled |
| `NOTION_API_TOKEN` | all Notion access | notion.so/my-integrations, then share the target page with the integration |
| `NOTION_TWEET_DRAFTS_DB_ID` | publishing | Written automatically by `setup.py` |
| `NOTION_RESPONSE_CALENDAR_DB_ID` | engagement | The Response Calendar database ID |
| `NOTION_DISCOVERY_DB_ID` | account discovery | The Discovery Database ID |
| `NOTION_PAPER_OUTREACH_DB_ID` | paper outreach | The Paper Outreach database ID (created by hand, see [Pipeline 3](#pipeline-3-paper-outreach)) |
| `NOTION_PAPER_AUTHORS_DB_ID` | paper outreach | The Paper Authors database ID (created by hand, same section) |
| `OPENAI_API_KEY` | paper outreach | Drafts blurbs and outreach messages. Everything else in the pipeline is required. |
| `OPENAI_MODEL` | paper outreach | Optional, defaults to `gpt-4o-mini` |
| `OPENALEX_MAILTO` | paper outreach | Optional, a contact address puts paper lookups on OpenAlex's faster polite pool |
| `SEMANTIC_SCHOLAR_API_KEY` | paper outreach | Optional, but without one Semantic Scholar rate-limits nearly every request |
| `OUTREACH_FOLLOWUP1_DAYS`, `OUTREACH_FOLLOWUP2_DAYS` | paper outreach follow-ups | Optional, default 6 and 10. See [Following up](#following-up) |

`NOTION_API_TOKEN` is distinct from Claude Code's own Notion connection. The
latter exists only inside a live chat session, whereas the posting scripts run
unattended and require their own credential.

The X and Gmail credentials each require setting up an OAuth app in the
respective developer console — [docs/credentials.md](docs/credentials.md)
walks through both, click by click.

### Initial setup

Run once, in this order:

```bash
.venv/bin/python gtm_agent/smoke_test.py <username>                    # 1. verify auth
.venv/bin/python gtm_agent/setup.py <notion-page-url> <your-username>  # 2. bootstrap
.venv/bin/python gtm_agent/x_oauth_login.py                            # 3. authorize posting
```

`setup.py` creates the `Tweet Drafts` database under the given Notion page with
the full schema, writes its ID into `.env`, and seeds `voice_corpus.json` from
your recent posts (up to 30 short-form entries and 10 long-form). It refuses to
run a second time unless invoked with `--force-new-db`.

`x_oauth_login.py` opens a browser for authorization, captures the redirect on
`127.0.0.1:8765`, and stores a refreshable token in `x_oauth_token.json` (which is
gitignored). Re-run it if that file is deleted or the refresh token is revoked.
It also grants the `dm.write` scope, needed for `send_outreach.py` to send X DMs.

`gmail_oauth_login.py` is the equivalent for outreach email: it captures the
redirect on `127.0.0.1:8766` and stores a refreshable token in
`gmail_oauth_token.json` (gitignored), scoped to `gmail.send` only. Only needed
for the paper-outreach pipeline.

## Pipeline 1: Engagement

### Configuring sources

`interests.md` is plain markdown containing `## Accounts` and `## Topics`
sections. Only `-` bullets are parsed, so prose and notes may appear anywhere in
the file without affecting behaviour.

You can populate the Accounts section manually, or have the system propose
candidates:

```bash
.venv/bin/python gtm_agent/discover_accounts.py             # stage candidates
.venv/bin/python gtm_agent/discover_accounts.py --promote   # Approved to interests.md
```

The first form searches your topics, collects post authors, filters out accounts
below `--min-followers` (default 500), and stages them in the Discovery Database
with `Review Status = New`. After you mark the useful ones `Approved` in Notion,
`--promote` appends them to `interests.md`. The manual review gate is intentional:
an account only begins consuming read budget in `discover.py` once you have
approved it.

### Discovering posts

```bash
.venv/bin/python gtm_agent/discover.py              # stage into Response Calendar
.venv/bin/python gtm_agent/discover.py --dry-run    # preview without writing
.venv/bin/python gtm_agent/harvest_and_rank.py      # legacy: prints only, accounts only
```

Fetches from configured accounts and topics, drops thread continuations
(`2/ 3/ …` self-replies — only thread heads and standalone posts are staged;
reply drafting reads the full thread from the head for context), ranks by
engagement, deduplicates against both a local seen-set (`gtm_agent.db`) and
rows already present in the Response Calendar, then writes the top `--limit`
results (default 10) with `Status = New`. All operations against X are
read-only; the script never likes, replies, or posts.

### Monitoring mentions

```bash
.venv/bin/python gtm_agent/check_mentions.py <your-username>
```

Replies to your posts, @-mentions, and quotes are otherwise invisible to the
system. These are staged into the same Response Calendar, so curation and reply
drafting operate on them unchanged.

### Curating

The `draft-x-replies` skill runs the discovery script, drafts the full option
set on every new row, and *advises* on priority in its report — but it never
changes `Status` on its own. Rows arrive as `New` and stay `New` until you
review them in Notion: reject the junk, mark the keepers, promote what you
want to send. The skill's relevance ranking (from your standing criteria plus
what you've previously `Posted` versus `Rejected`) exists to make that review
fast, not to replace it.

**Important:** `Status` is the Response Calendar's single lifecycle column:

| Value | Meaning | Set by |
|---|---|---|
| `New` | freshly staged by discovery, drafts filled in | the pipeline |
| `Reviewed` | you looked at it, worth keeping around | you |
| `Ready to post` | option chosen, ready to send | you (or the skill, on your ask) |
| `Scheduled` | reply pushed to Typefully, awaiting its `Scheduled Time` | the pipeline (Typefully-eligible rows only) |
| `Posted` | you actually replied on X | **you only** (or the pipeline, once Typefully confirms a `Scheduled` reply published) |
| `Stale` / `Rejected (irrelevant)` / `Rejected (IDK what to say)` | exits | you |

`Posted` doubles as the learning signal: it is positive evidence, the
`Rejected (…)` values are negative, and everything else is explicitly
neutral — no reply occurred, but the content was not necessarily unsuitable.
The skill never sets `Posted`; doing so would corrupt the signal it depends
on. The row also carries `Added Date`, when it entered the calendar
(`Original Tweet Date` records when the post itself was tweeted).

### Drafting replies

The `draft-x-replies` skill routes each newly staged row: tweets referencing
external content (links, quote-tweets, threads, named papers/repos) get a
research subagent — all spawned in parallel — that resolves the links, reads
the thread, looks the sources up on the web, and only then drafts;
self-contained tweets (pure opinions, quips) are drafted directly with no
subagent, so tokens go to research only where research exists to do. Every
row ends up with `Reply 1/2/3` (three substantively different angles) plus a
suggested `Retweet Message` (clear it for a plain retweet), written in your
voice from the same `voice_corpus.json` used by the publishing pipeline.
Rows whose links can't be resolved are flagged as shallower in the report. This is the connection
between the two pipelines: discovery locates the post, and the corpus
supplies the voice.

You then set `Selected` to your preferred option (editing that reply field in
place if you want changes), a `Scheduled Time`, and flip `Status = Ready to
post` — by hand, or by asking the skill to stage it. `draft-x-replies` itself
never posts: it writes the three `Reply` fields and recommends one, sets
`Selected` and `Ready to post` only when you tell it to, and never sets
`Posted` — that records what actually went out.

Posting the staged queue is a separate, explicitly-invoked step —
`publish-x-replies`, a two-step trigger for `gtm_agent/post_response_calendar.py`
and `gtm_agent/sync_typefully_status.py` — not something that runs unattended
off drafting. `Selected` decides the path: `Reply 1/2/3`/`Self-Written Reply`
rows push to Typefully as a reply (`reply_to_url` = the original tweet) as
soon as they're `Ready to post`, flipping `Status = Scheduled` on a
successful push, and Typefully fires at `Scheduled Time` from there;
`Retweet` rows (plain or quote) are unaffected by Typefully and still
post directly via the X API, gated locally on `Scheduled Time` having passed.
There is deliberately no `Like` action — auto-like is the specific pattern
`x-req.md` §2.5 calls out as the cause of account suspensions, and a like has
no authored text to justify automating it, so it was cut from `Selected`
entirely rather than wired up.

On a direct retweet/quote-retweet, the script appends the posted text to
`voice_corpus.json` itself (`post_type: "quote"`); on a Typefully-published
reply, `sync_typefully_status.py` does the same (`post_type: "reply"`) once
it confirms the draft actually published — so replies/quotes posted this way
don't need a separate corpus-sync step. `gtm_agent/sync_replies.py` still
exists as a backfill for anything posted outside this flow — e.g. by hand,
directly on X — keyed by Notion page ID so it's safe to re-run on rows
already marked `Posted` manually. Plain retweets carry no text either way,
so nothing is harvested for those.

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

The `polish-x-drafts` skill rewrites the note in your voice, writes the result to
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
.venv/bin/python gtm_agent/post_ready.py               # one due row per run (article only, see below)
.venv/bin/python gtm_agent/post_all_due.py              # push single/multi-thread to Typefully + post due articles directly
.venv/bin/python gtm_agent/sync_typefully_status.py     # reconcile previously-pushed Typefully drafts
```

Alternatively, ask Claude to post your ready tweets; the `publish-x-queue` skill
is a two-step trigger for `post_all_due.py` then `sync_typefully_status.py`.

`post_type` decides the path. `single-thread`/`multi-thread` rows with no
`Typefully Draft ID` yet are pushed to Typefully as soon as `Stage = Ready to
post` — not gated on `Scheduled Time` locally, since Typefully takes the
`Scheduled Time` as its own `publish_at` and owns firing at that moment from
there. On a successful push, `Stage` is set to `Scheduled` (and stays there)
until `sync_typefully_status.py` confirms the draft actually published and
flips it to `Posted`. `article` rows are unaffected by Typefully (not a
supported format there) and keep the original behavior exactly: acted on
only once `Scheduled Time` has passed, posted directly via the X API,
`Stage` going straight to `Posted`. Rows without a `Scheduled Time`, or with
one still in the future, are never touched by either path.

On a direct-post success (`article`), `Stage` is set to `Posted` and the post
is appended to `voice_corpus.json`. On failure (either path), the error is
written to `Post Error` and `Stage` is left unchanged so the row is retried
on the next run.

**Pushing to Typefully is still a manual, explicitly-invoked step** — there is
no cron integration in this repo by design, and that hasn't changed. What has
changed for eligible post types is what happens *after* the push: Typefully's
own scheduler fires unattended at `Scheduled Time`, rather than you needing to
re-run `post_all_due.py` at exactly that moment. Articles, retweets/quote-
retweets, and DMs have no such handoff — they still post immediately, directly,
the moment you run the script past their due time, and each one costs money and
cannot be undone. Run everything manually, and do so several times before
trusting it, same as always.

#### Scheduled publishing via Typefully

Typefully's v2 API is a compose-and-schedule tool for new content — it covers
posts, threads, and replies (via `reply_to_url`), but has no generic "retweet
this" or "send a DM" action. Concretely:

| Source | Type | Path |
|---|---|---|
| Tweet Drafts | `single-thread` | Typefully |
| Tweet Drafts | `multi-thread` | Typefully (thread = `posts` array) |
| Tweet Drafts | `article` | Direct X API — not a Typefully format |
| Response Calendar | reply (`Selected` = a `Reply`/`Self-Written Reply`) | Typefully |
| Response Calendar | retweet/quote-retweet (`Selected` = `Retweet`) | Direct X API — no confirmed retweet endpoint on Typefully |
| Paper Authors | X DM (`Send Via` = X) | Direct X API — Typefully has no DM support at all |

So this is additive, not a replacement: your X OAuth app/token stays required
regardless, for Articles, retweets, and DMs. To use Typefully, get an API key
from typefully.com/settings/integrations, then find your social set id with:

```bash
curl -s "https://api.typefully.com/v2/social-sets" -H "Authorization: Bearer $TYPEFULLY_API_KEY"
```

Set both as `TYPEFULLY_API_KEY` and `TYPEFULLY_SOCIAL_SET_ID` in `.env`. The
free Typefully tier includes API access with 1 social set, capped at 15
posts/month — enough for light posting cadences; paid tiers remove the cap.
Check your recent `Posted` row volume across Tweet Drafts + Response Calendar
against that cap before committing to a paid tier.

### Partial failure cases

One failure mode leaves real state on X and deliberately does not auto-retry,
as a retry would compound the problem rather than resolve it, and requires
manual intervention:

- **An Article draft created but not published.** The draft exists on X. The error
  message records the draft ID. Retrying would create a second draft.

Threads no longer have an equivalent partial-failure case in this pipeline —
`multi-thread` rows are pushed to Typefully as a single draft (its `posts`
array), and Typefully publishes the whole thread atomically on its end rather
than this repo posting each reply-chained tweet itself.

## Pipeline 3: Paper outreach

A separate, Notion-only workflow for reaching out to research paper authors.
It does not share the voice corpus or the review-gate machinery above; see
`Req/paper-outreach.md` for the original feature idea. Discovery, drafting,
sending, reply detection, and a two-step follow-up cadence are implemented;
meeting scheduling and calendar sync are not.

### Setup

Unlike the Tweet Drafts database, the two databases this pipeline needs are
not created for you. In Notion, create:

- **Paper Outreach**: `Paper Name` (title), `Paper link` (url), `Notes`
  (text), `Status` (select: `New`, `Needs Review`, `Blurb Ready`), `Blurb`
  (text)
- **Paper Authors**: `Author` (title), `Paper` (relation to Paper Outreach),
  `Role` (select: `Corresponding`, `Co-author`), `Affiliation` (text), `Email`
  (email), `X Handle` (text), `LinkedIn` (url), `Selected` (checkbox, not
  currently used by any script — `Send Via` is what authorizes a send),
  `Send Via` (select: `Email`, `X`, `LinkedIn` — left blank by drafting, set
  by hand when you're ready to send), `Subject` (text, Email only — X DMs
  have no subject line and leave it blank), `Message` (text, body only —
  Email/X), `LinkedIn Note` (text, ≤200 chars, LinkedIn's own cap on
  connection-request notes — drafted separately from `Message`, never sent
  automatically, see below), `Post Error` (text, what went wrong on a
  failed/skipped send — cleared on a later successful send), `Status`
  (select: `Needs Handles`, `Draft Ready`,
  `Needs Review`, `Message Drafted`, `Sent`, `Followup 1 Sent`,
  `Followup 2 Sent`, `Replied`), `Scheduled Time` (date, optional — see
  below), `First Sent` (date), `Last Sent` (date), `Thread Ref` (text),
  `Followup 1 Message` (text), `Followup 2 Message` (text)

The last five Paper Authors fields (`First Sent` through `Followup 2
Message`) are only used by the follow-up cadence described below — skip them
if you only intend to send a single message per author by hand.

Share both with your Notion integration, then set `NOTION_PAPER_OUTREACH_DB_ID`
and `NOTION_PAPER_AUTHORS_DB_ID` in `.env`.

### Running it

Add a paper to the Paper Outreach database with a `Paper Name` and,
ideally, a `Paper link` (arXiv, DOI, or title also works), then:

```bash
.venv/bin/python gtm_agent/fetch_paper_authors.py               # run 1: resolve authors, fetch handles, draft the blurb
.venv/bin/python gtm_agent/fetch_paper_authors.py --all-authors  # fetch every author instead of just the top 5
```

This resolves the paper via OpenAlex (falling back to Semantic Scholar),
stages its top authors — corresponding authors first, since author order
itself is a signal — into Paper Authors, and writes a `Blurb` from the
abstract plus your `Notes`. Emails are filled in only when the arXiv PDF
itself states one; X handles come from a homepage on file or, failing that, a
best-effort X search that is marked low-confidence and still needs a glance.
Rows without a confirmed email or handle are left `Needs Handles` for you to
fill in by hand — or to research automatically:

```bash
uv sync --extra research                                      # one-time, installs claude-agent-sdk
.venv/bin/python gtm_agent/research_authors.py                 # run 1.5: web-research Needs Handles rows
.venv/bin/python gtm_agent/research_authors.py --dry-run       # research and print, write nothing
```

This optional step fans out one Claude Agent SDK subagent per `Needs
Handles` author — each searches the open web (homepages, lab pages, Google
Scholar, X, LinkedIn) on Haiku, in parallel, and reports only values a
source explicitly states, with the source cited. Findings fill the empty
contact fields and the row moves to `Needs Review` — never straight to
`Draft Ready`, because a web match is a candidate, not a confirmation. The
cited evidence prints to the console for your glance; fields already filled
in are never overwritten, and rows where nothing was found stay `Needs
Handles`. The agent is restricted to web search and fetch (no shell, no file
writes — all Notion writes happen in the script), and unlike everything else
in this project it spends Anthropic API tokens, capped at `--limit` authors
per run (default 25).

Then draft messages for everyone with a contact on file — this never touches
`Send Via` at all, so nothing needs to be set in Notion first:

```bash
.venv/bin/python gtm_agent/send_outreach.py --draft-only         # run 2: draft only, never sends
```

This drafts a `Subject` + `Message` for every author who doesn't have one
yet and has an Email, X Handle, or LinkedIn on file, always in Email format
(subject + body) regardless of which contact they actually have — which
parts get used depends on whatever channel is picked at send time, not on
this. Anyone with a LinkedIn URL on file additionally gets a `LinkedIn Note`
drafted separately — a distinct field, hard-capped at 200 characters
(LinkedIn's own limit on connection-request notes), truncated defensively
if the model overshoots. Pulls tone from your own previously `Sent` messages
as few-shot examples. Authors with no contact info at all are skipped and
reported. `Status` becomes `Message Drafted`; nothing is ever sent in this
mode, and `Send Via` is left exactly as it was (blank, unless you'd already
set it yourself).

Review the drafts in Notion, edit anything you want, and set `Send Via`
(`Email`/`X`/`LinkedIn`) by hand on whoever you want to actually reach —
that choice alone is what authorizes a send, nothing else is checked. Then:

```bash
.venv/bin/python gtm_agent/send_outreach.py                     # run 3: draft (if needed) and send
```

This sends to every author with a `Send Via` set — anyone still blank is
left alone entirely. `Send Via` also decides what gets used: `Email` sends
the Subject + Message together; `X` sends the Message only, Subject dropped;
`LinkedIn` uses the separate `LinkedIn Note` field, not `Message` at all.
`Scheduled Time` is an optional additional gate: leave it blank to send
immediately (unchanged default behavior), or set a future time to hold that
author until a later run — this is a plain local due-time check, not a
Typefully push, since Typefully has no DM support and these sends always go
through the direct Gmail/X API. Anyone still missing the relevant field for
their channel (`Message` or `LinkedIn Note`) gets one drafted first, same as
run 2. Then it attempts to send:

| Channel | Requires | Behaviour |
|---|---|---|
| Email | `gmail_oauth_login.py` run, `Email` on file | Sends via Gmail; `Status` becomes `Sent` |
| X | `x_oauth_login.py` run with `dm.write`, `X Handle` on file | Sends a real DM; `Status` becomes `Sent` |
| LinkedIn | — | No safe API exists to automate this — LinkedIn has no official connection-request API, and the unofficial ones need your raw password and risk account restriction. Always drafts a `LinkedIn Note` and prints it for you to paste in by hand; `Status` stays `Message Drafted` |

Whatever went wrong on a failed or skipped send (no OAuth token, no contact
on file for that channel, LinkedIn's lack of a send API, an API error) is
written to `Post Error` so you can see why directly in Notion; a later
successful send clears it. A hand-written `Message` or `Subject` is always
used as-is and never overwritten. Rows already `Sent` are skipped on re-run,
so `send_outreach.py` is safe to run repeatedly as you fill in more authors.
A successful Email or
X send also records `First Sent`/`Last Sent` and, for Email, the Gmail
thread id — what the follow-up run below needs to check for a reply and, if
there isn't one, reply in the same thread.

### Following up

```bash
.venv/bin/python gtm_agent/send_followups.py             # run 3: check replies, send due follow-ups
.venv/bin/python gtm_agent/send_followups.py --dry-run   # preview without sending or updating Notion
```

Run this regularly (by hand, or on a schedule you set up yourself — there is
no built-in cron, consistent with the rest of this project). Each run, for
every Email/X author in `Status` `Sent`, `Followup 1 Sent`, or `Followup 2
Sent`:

1. **Checks for a reply first**, regardless of timing. If found, `Status`
   becomes `Replied` and that author is never messaged again by this
   pipeline.
2. Otherwise, if enough time has passed since the last message, drafts and
   sends the next follow-up — a short nudge, not a re-pitch — via
   `outreach_llm.followup_message()`, using the same `Sent`-message tone
   examples as the initial send.

| Follow-up | Fires after | Configurable via |
|---|---|---|
| 1 | `OUTREACH_FOLLOWUP1_DAYS` (default 6) since the initial message | `.env` |
| 2 | `OUTREACH_FOLLOWUP2_DAYS` (default 10) since Follow-up 1, not since the initial message | `.env` |

After Follow-up 2, the script keeps checking for a reply on later runs but
never sends a third message.

Reply detection needs read access this pipeline didn't previously require:
Email checks the Gmail thread for a message from anyone but you (`gmail.readonly`
scope), X checks the DM conversation for a message from the other participant
(`dm.read` scope). Both scopes were added to the existing OAuth flows — if your
`gmail_oauth_token.json` or `x_oauth_token.json` predates this feature, re-run
`gmail_oauth_login.py` / `x_oauth_login.py` to pick them up. LinkedIn has
neither a send nor a read API, so those rows are left alone; check replies
there yourself.

## The voice corpus

`voice_corpus.json` (gitignored) is the sole source of style exemplars for
`polish-x-drafts` and `draft-x-replies`:

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
.venv/bin/python gtm_agent/fetch_metrics.py
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

## Founder memory

`memory/` (gitignored) is a small set of markdown files that summarize what
the drafting skills have actually observed about the founder — voice,
topics/accounts/companies worth engaging, and cross-cutting likes/dislikes —
generated from real activity rather than hand-written once and left stale:

- `MEMORY.md`: index, with a confidence level per file
- `x-voice.md` / `x-topics.md`: tone and topic signal for the engagement
  and publishing pipelines, from `voice_corpus.json` and the Response
  Calendar/Tweet Drafts `Posted`/`Rejected` history
- `outreach-voice.md` / `outreach-topics.md`: the same for paper outreach,
  from the Paper Authors and Paper Outreach databases
- `preferences.md`: standing likes/dislikes already codified in
  `draft-x-replies/style.md` and `SKILL.md`, collected in one place

Each file states its own confidence and says outright when history is too
thin to support a claim, rather than inventing a pattern. `draft-x-replies`,
`polish-x-drafts`, and `paper-outreach` all read the relevant file(s)
alongside their existing corpus/config sources. A founder can add durable
notes directly under each file's `## Founder notes` section — that section
is preserved whenever the automatic update below regenerates the rest.

Updates happen automatically, no explicit request needed, in two ways:
every skill that touches Notion or `voice_corpus.json`
(`draft-x-replies`, `publish-x-replies`, `publish-x-queue`, `paper-outreach`,
`publish-paper-outreach`, `polish-x-drafts`) runs the shared procedure in
`.claude/memory-update-procedure.md` as its own last step, on every run —
a fast no-op when nothing new happened, an update to just the affected
file(s) when it did; and — per `CLAUDE.md` (symlinked as `AGENTS.md`, so this
applies whether the session is Claude Code or Codex) — any opinion the
founder states directly gets appended to the relevant file's `## Founder
notes` in that same turn.

## Project layout

**User-editable configuration**

- `interests.md`: accounts and topics to discover from
- `.env`: credentials

**Generated files (all gitignored)**

- `voice_corpus.json`: style exemplars
- `memory/`: observed founder voice/topics/preferences (see "Founder memory" above)
- `gtm_agent.db`: seen-set and user ID cache
- `x_oauth_token.json`: publishing token
- `gmail_oauth_token.json`: outreach email token

**Library and scripts** (`gtm_agent/`) — one flat package; library modules are imported by the scripts below and by each other.

| Module | Responsibility |
|---|---|
| `config.py` | Environment variable loading |
| `x_client.py` | X API: reads, posts, threads, Articles, metrics |
| `x_oauth.py` | OAuth 2.0 PKCE login and token refresh |
| `notion_client.py` | Notion API; owns `TWEET_DRAFTS_SCHEMA` |
| `typefully_client.py` | Typefully v2 API: create/get a draft (single post, thread, or reply) |
| `interests.py` | Parses `interests.md` |
| `store.py` | SQLite seen-set and user ID cache |
| `ranking.py` | Engagement scoring with optional recency decay |
| `harvest.py` | Account fetch, deduplication, ranking |
| `posting.py` | Thread and Article parsing/validation; `push_row_to_typefully()`/`push_response_row_to_typefully()` (Typefully-eligible types) and `post_row()`/`post_response_calendar_row()` (direct X API — Articles, retweets) |
| `voice_corpus.py` | Corpus load, save, append, and metric attachment |
| `gmail_oauth.py` | OAuth 2.0 PKCE login and token refresh for Gmail |
| `gmail_client.py` | Gmail API: sending outreach email |
| `scholar.py` | Paper/author lookup via OpenAlex and Semantic Scholar |
| `paper_pdf.py` | Corresponding-author emails parsed from a paper's own arXiv PDF |
| `handle_search.py` | Best-effort X handle discovery for paper authors |
| `outreach_llm.py` | OpenAI-backed blurb and outreach message drafting |

| Script | Purpose |
|---|---|
| `setup.py` | One-time bootstrap: creates the database, seeds the corpus |
| `smoke_test.py` | Single-call authentication check |
| `x_oauth_login.py` | One-time publishing authorization |
| `discover.py` | Fetch, rank, and stage posts into the Response Calendar |
| `discover_accounts.py` | Find accounts by topic; `--promote` adds approved ones to `interests.md` |
| `check_mentions.py` | Stage replies and mentions into the Response Calendar |
| `harvest_and_rank.py` | Legacy print-only, accounts-only variant |
| `post_ready.py`, `post_all_due.py` | Push single/multi-thread Tweet Drafts rows to Typefully; publish due `article` rows directly |
| `post_response_calendar.py` | Push due reply rows to Typefully; publish due retweet/quote-retweet rows directly |
| `sync_typefully_status.py` | Reconcile previously-pushed Typefully drafts — flips `Posted` once Typefully confirms publication |
| `fetch_voice_corpus.py` | Seed or merge corpus entries from your timeline |
| `fetch_metrics.py` | Attach post analytics to corpus entries |
| `sync_replies.py` | Backfill hand-posted replies into the corpus |
| `sync_posted.py` | Import X history into Notion for visibility |
| `gmail_oauth_login.py` | One-time outreach-email authorization |
| `fetch_paper_authors.py` | Resolve a paper's authors, handles, and blurb (paper-outreach run 1) |
| `research_authors.py` | Optional subagent web research for authors left `Needs Handles` (paper-outreach run 1.5) |
| `send_outreach.py` | Draft and send outreach messages (paper-outreach run 2) |
| `send_followups.py` | Check for replies, send due follow-ups (paper-outreach run 3, run repeatedly) |

**Skills** (`.claude/skills/`)

| Skill | Purpose |
|---|---|
| `polish-x-drafts` | Rough note to voice-matched draft |
| `draft-x-replies` | Run discovery, prune using the `status` signal, then write three reply options in your voice for the shortlist |
| `publish-x-queue` | Two-step trigger: `post_all_due.py` (push/post), then `sync_typefully_status.py` (reconcile) |
| `publish-x-replies` | Two-step trigger: `post_response_calendar.py` (push/post), then `sync_typefully_status.py` (reconcile) |

## Project status

**Most of the pipeline has not yet been run against the live X or Notion APIs.**
Every other code path is verified offline against mocked calls; live
verification there is blocked on credentials and X API credits. The Typefully
integration is the exception: `typefully_client.py`'s `create_draft()`/
`get_draft()` and the live Notion schema migration (`Typefully Draft ID` on
Tweet Drafts/Response Calendar, `Scheduled Time` on Paper Authors) have been
exercised against the real Typefully and Notion APIs. The full push-then-
reconcile flow through `post_all_due.py`/`post_response_calendar.py`/
`sync_typefully_status.py` has not yet been run against a real queued row.

Implemented and offline-verified:

- Discovery across accounts and topics, with ranking, deduplication, and staging
- Account discovery and mention monitoring, both staged for manual review
- Voice-matched drafting for all three post types, plus rejected-draft retry
  informed by Notion comments
- Reply drafting sharing the publishing pipeline's voice corpus
- Reply publishing for staged Response Calendar rows via Typefully
  (`post_response_calendar.py` + `sync_typefully_status.py`), owned by
  Typefully's own scheduler past the push; retweet/quote-retweet publishing
  stays on the direct X API, gated on `Scheduled Time`; `Like` deliberately
  unsupported
- Publishing for all three Tweet Drafts post types: `single-thread`/
  `multi-thread` via Typefully (pushed, then reconciled once published),
  `article` via the direct Articles API gated on `Scheduled Time`, with the
  Article partial-failure path handled
- Corpus seeding, automatic growth on publication, performance metric attachment,
  and sent-reply ingestion
- Paper-outreach author resolution, handle discovery, and blurb/message
  drafting, with real sending over Gmail and X DM
- Paper-outreach reply detection and a two-follow-up cadence, both configurable
- Optional parallel-subagent web research for authors missing handles
  (`research_authors.py`), gated behind `Needs Review`

Known limitations:

| Limitation | Detail |
|---|---|
| Topic search unverified | Recent-search may not be callable on pay-per-use billing (`x-req.md` open item 2). Degrades gracefully. |
| No automatic polling | `polish-x-drafts` must be invoked; it does not watch for `Ready for AI Review` rows. |
| No scheduler for the direct-API paths | Articles, retweets/quote-retweets, and DMs still post immediately, the moment you manually run the relevant script past their `Scheduled Time`. `single-thread`/`multi-thread`/reply posts no longer have this limitation — Typefully fires those unattended once pushed. |
| Weak `sync_posted.py` deduplication | Matches on exact text rather than tweet ID, since the `Posted URL` property was removed. Avoids re-importing on every run. |
| Articles require X Premium | A sparse `articles` bucket also means weak long-form voice matching until several are published. |
| Paper-outreach follow-ups are capped at two | Matches the requested cadence; nothing is sent after Follow-up 2 goes unanswered, and meeting scheduling/calendar sync from `Req/paper-outreach.md` remain unimplemented. |
| Paper Outreach/Paper Authors databases are hand-created | Unlike Tweet Drafts, `setup.py` does not provision them; see [Pipeline 3](#pipeline-3-paper-outreach). |
| LinkedIn outreach send and reply tracking are, by design, permanently manual | No official LinkedIn API exists for sending connection requests; unofficial ones need your raw password and risk account restriction, so this repo won't automate it. `LinkedIn Note` always drafts (≤200 chars) for manual copy-paste, and LinkedIn rows are excluded from `send_followups.py`. |
| Author research spends Anthropic tokens | `research_authors.py` is the one component that bills an Anthropic API key (via the Claude Agent SDK); it is optional, capped per run, and its findings always land in `Needs Review` rather than being trusted. |

## Roadmap

Ordered approximately by impact on day-to-day use.

### Closing the remaining manual loops

- **Automatic polling.** `polish-x-drafts` currently must be invoked explicitly. A
  watcher that picks up `Ready for AI Review` rows would make the publishing
  pipeline self-feeding: drop a rough note into Notion, return to a finished
  draft.
- **Scheduling for the direct-API paths.** `single-thread`/`multi-thread`/reply
  posts now schedule themselves via Typefully once pushed. Articles,
  retweets/quote-retweets, and DMs still require a manually-timed script run.
  Cron and auto-spacing logic were deliberately removed once already, so any
  reintroduction there should be opt-in and must preserve the one-post-per-run
  safety cap.
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
- **Direct message handling for the engagement pipeline.** Cut by choice, and
  reasonably kept cut: direct messages carry higher stakes at lower volume
  than public replies. (X DM sending does now exist, but only as a one-shot
  send within the separate [paper-outreach pipeline](#pipeline-3-paper-outreach).)

### Explicitly out of scope

- **Auto-liking, auto-replying, or publishing without approval.** This is the
  design constraint the entire system is built around, not a limitation to be
  removed later. Removing the review gate would make the tool actively hazardous
  to the account it exists to grow.
- **Follower-count dashboards.** Inexpensive to build and largely unactionable.
  Per-post engagement rate already answers the useful form of that question.
