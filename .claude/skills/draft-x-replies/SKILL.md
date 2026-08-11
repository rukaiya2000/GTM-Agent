---
name: draft-x-replies
description: Fetch new posts into the Response Calendar and draft Reply 1/2/3 plus a suggested retweet message for every row — hybrid routing spawns parallel research subagents only for tweets referencing external content (links, threads, papers), grouped by shared source; self-contained tweets are drafted inline. Statuses belong to the author; the skill only advises. Use when the user asks to find posts to engage with, discover new posts, draft replies, or work through their Response Calendar.
---

# Draft X Replies

Two jobs: **fetch** candidates (deterministic script, costs money per read),
then **draft the full option set** for every new row — three replies plus a
suggested retweet message, each **grounded in the sources the tweet actually
references**. Drafting fans out across parallel subagents, one per row.
**You never post anything**, and **you never change `Status` on your own** —
every fetched row stays `New` until the author moves it. Curation is advice
in your report, not writes. Automated engagement is what gets accounts
suspended (`x-req.md` §2.5).

Database: `ec8eb9c5f591820393d101733079983f` (Response Calendar — the single
source of truth, on the GTM page). Fetch it first: the response names its
`collection://…` data source id if you need SQL. **If the fetch 404s, the
Notion connector is attached to the wrong workspace** — tell the user to point
Claude's Notion connection at the workspace holding the GTM page; do not guess
at a different database.

## The row lifecycle — who sets what

`Status`: `New` → `Reviewed` → `Ready to post` → `Posted`, with `Stale`,
`Rejected (irrelevant)`, `Rejected (IDK what to say)` as exits.

**Every `Status` transition is the author's.** New rows arrive as `New` and
stay `New` — they review, edit drafts, reject, and promote themselves. The
only exception: when they explicitly ask you to stage a row ("stage this one",
"use reply 2", "just retweet it"), set `Selected` (and `Retweet Message` if
quoting), `Scheduled Time`, and `Status = Ready to post`. Never set any other
status, and never set `Posted` under any circumstances — it records that a
reply/retweet actually went out and is the signal your advice learns from.

Fields per row: `Reply 1/2/3` (three reply options), `Retweet Message`
(suggested quote text — the author clears it for a plain retweet), `Selected`
(`Reply 1/2/3`, `Self-Written Reply`, or `Retweet` — their choice; there's no
`Like` option, that action was cut entirely), `Self-Written Reply` (theirs),
`Scheduled Time` (when it should actually post — required for `Ready to
post` rows), `Added Date` (when the row entered the calendar), `Original
Tweet Date` (when the post was tweeted).

Posting is a separate, explicitly-invoked step — the `publish-x-replies`
skill, not this one. This skill only drafts and stages; it never calls the X
API to post.

## Phase 1 — Fetch new candidates

```bash
.venv/bin/python scripts/discover.py            # add --dry-run to preview
```

Reads `interests.md` for accounts and topics, ranks by engagement, skips
anything already seen or already in the calendar, and stages the top 10 as
`Status = New`. Report its output as-is; don't re-rank on engagement
yourself, that's already done.

## Phase 2 — Draft via parallel research subagents

Eligible rows: `Status = New` with an empty `Reply 1`. Skip rows that already
have replies (unless asked to redo them) and rows where `Self-Written Reply`
is filled.

**Route each row first — subagents are for research, not for every row:**

- **Needs research → subagent:** the tweet contains a link, is a
  quote-tweet, is a thread head (the thread must be read), or names a
  paper, benchmark, repo, or product that has to be looked up.
- **Self-contained → draft inline yourself:** a pure opinion, prediction,
  or quip with no external reference and nothing to fetch. Spawning an
  agent here only burns tokens; apply `style.md` and write the drafts
  directly.

**Group before spawning:** rows that reference the same source or belong to
the same conversation share one subagent — it researches the source once
and drafts for every row in its group. Never send N agents to read the
same paper.

**Spawn all the research subagents in a single message so they run
concurrently** — never one at a time, and never two for the same row.
Subagents research and draft; they return JSON and **never touch Notion**.
You collect the results, write them back alongside your inline drafts, and
compile one report. If subagents are unavailable in the session, run the
research procedure yourself, sequentially, for the rows that need it.

### Each subagent's task

Give every subagent its group's rows (tweet text, URL, date, and Notion
page id per row) and these instructions — **do not paste style or voice
rules into the prompt**; instead instruct it to first read
`.claude/skills/draft-x-replies/style.md` and `voice_corpus.json` (repo
root) and follow them:

1. **Research before drafting — this is the point.** Resolve every t.co
   link. Open quote-tweets and read what was quoted. If the tweet is a
   thread head (starts with "1/", or clearly continues), **read the rest of
   the thread from its URL** — the reply goes on the head, but the whole
   thread is context (discovery stages only heads; the continuations exist
   and often carry the substance). If a paper, benchmark, repo, or product
   is named or linked, find it on the web (arXiv page, project site, repo
   README) and read the abstract and key claims. Replies must engage with
   what the source actually says — a reply that only orbits the tweet's own
   phrasing is a failed draft. Budget: the abstract or first screen of each
   source, not a 40-page read.
2. If a link genuinely can't be resolved (deleted post, paywall,
   media-only), draft from the tweet text alone and say so.
3. Reply with **only** a JSON array — one object per row in your group, no
   other text:

```json
[{"page_id": "<the Notion page id you were given for this row>",
  "reply_1": "...", "reply_2": "...", "reply_3": "...",
  "retweet_message": "...",
  "grounding": "<one line naming the sources actually read>",
  "ungrounded": false}]
```

### Voice, style, and rules — `style.md`

The voice guidance, the author's standing style direction, the three-angles
requirement, and the hard rules all live in **`style.md` next to this
file** — the single definition, so prompts and skill can't drift. Read it
yourself before drafting inline rows, and instruct every subagent to read
it (plus `voice_corpus.json` in the repo root) as its first step instead of
pasting the rules into each prompt.

### Writing back (you, never the subagents)

Collect every subagent's JSON, then write `Reply 1/2/3` and
`Retweet Message` to each row via `notion-update-page`, directly, no chat
approval first — review happens in Notion. Leave `Status = New`. A subagent
that returns malformed JSON or times out: redo that row yourself rather than
leaving it blank.

## Phase 3 — Assess and prioritise (report only, no writes)

Rank the new rows for the report using the author's standing criteria — keep:
new RL environments; papers/posts on autonomously scaling agent evaluations,
benchmarks, or RL environments; data methods for scaling post-training
agents; well-thought-out opinions on scaling post-training, RL, or
data/environments; automatic harness engineering / auto-optimization. Focus:
computer/browser-use agents, tool use in enterprise workflows, long-horizon
agentic capabilities. Flag as likely-skip: promotional posts, engagement
bait, memes, shallow commentary, generic hype, low-info reposting, robotics
hardware, thread fragments (the reply belongs on the head), and posts too old
to still reply to.

Sharpen the ranking with the learned signal where history exists: rows the
author moved to `Posted` are positive evidence, `Rejected (…)` negative,
everything else neutral. Thin history means low-confidence advice — say so.

**These judgments go in your report only. Do not write them to `Status`.**

## Reporting

One report at the end: how many rows were staged and the subagent/inline
split (how many rows needed research versus were drafted directly), then
the rows ranked most promising first — for each, the three replies and the
retweet suggestion with a few words on the angle each takes, **what sources
were actually read** (from `grounding`; "none needed" for inline rows), and
which option you'd send. Call out any `ungrounded` rows so the author knows
those drafts are shallower. Then the likely-skips with a one-line reason
each. Flag anything unusual (empty corpus, failed sources, thin signal,
subagents redone by hand).
