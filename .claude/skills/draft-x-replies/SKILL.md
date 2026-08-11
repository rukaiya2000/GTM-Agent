---
name: draft-x-replies
description: Fetch new posts into the Response Calendar and draft the full option set for each — Reply 1/2/3 plus a suggested retweet message — so the author can review, edit, and choose. Statuses belong to the author; the skill only advises. Use when the user asks to find posts to engage with, discover new posts, draft replies, or work through their Response Calendar.
---

# Draft X Replies

Two jobs: **fetch** candidates (deterministic script, costs money per read),
then **draft the full option set** for every new row — three replies plus a
suggested retweet message — so the author can review, edit, and choose in
Notion. **You never post anything**, and **you never change `Status` on your
own** — every fetched row stays `New` until the author moves it. Curation is
advice in your report, not writes. Automated engagement is what gets accounts
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
quoting) and `Status = Ready to post`. Never set any other status, and never
set `Posted` under any circumstances — it records that they actually replied
on X and is the signal your advice learns from.

Fields per row: `Reply 1/2/3` (your three reply options), `Retweet Message`
(your suggested quote text — the author clears it for a plain retweet),
`Selected` (`Reply 1/2/3`, `Self-Written Reply`, `Like`, or `Retweet` — their
choice), `Self-Written Reply` (theirs), `Added Date` (when the row entered
the calendar), `Original Tweet Date` (when the post was tweeted).

## Phase 1 — Fetch new candidates

```bash
.venv/bin/python scripts/discover.py            # add --dry-run to preview
```

Reads `interests.md` for accounts and topics, ranks by engagement, skips
anything already seen or already in the calendar, and stages the top 10 as
`Status = New`. Report its output as-is; don't re-rank on engagement
yourself, that's already done.

## Phase 2 — Draft the full option set for every new row

For **every** row with `Status = New` and an empty `Reply 1` (skip rows that
already have replies unless asked to redo them, and rows where
`Self-Written Reply` is filled):

### Voice

Read the **`tweets`** bucket of `voice_corpus.json` — replies are short-form,
so the `articles` bucket is not relevant here. Entries with
`post_type: "reply"` or `"quote"` are things the author actually sent (via
`scripts/sync_replies.py`) — weight those highest. Entries carrying a
`metrics.engagement_rate` are measured performers; prefer higher ones, but
treat a missing metric as unmeasured, never as bad. Match the author's tone,
vocabulary, technical depth, and punctuation habits. If the file is missing
or nearly empty, say so and write plainly rather than inventing a voice.

A reply is not a broadcast post: it's responsive and conversational, assumes
the original post as context, and doesn't re-introduce what the reader can
already see. A retweet message is closer to a broadcast: it frames the post
for the author's followers in one or two sentences.

### The author's standing style direction

Where it conflicts with a corpus habit, this direction wins:

- technical and peer-level, in a founder/executive voice
- concise: **max 220 characters and 1–2 sentences each** (deliberately
  tighter than X's 280 limit)
- curious or additive — the goal is to engage researchers/builders and start
  a thoughtful conversation
- not salesy; don't mention the company unless directly relevant
- no emojis, no bulleting, no hashtags
- no jargon overload unless the tweet itself is highly technical
- sound natural on X, not like a memo

### What to write on each row

`Reply 1`, `Reply 2`, `Reply 3` — **three different angles**, not three
rewordings. Useful angles: add a concrete detail or counter-example; share
directly relevant first-hand experience; ask a specific genuine question;
respectfully complicate a claim; connect it to adjacent work.

`Retweet Message` — one suggested quote line framing the post, in the same
style. The author clears it if they'd rather plain-retweet.

Hard rules:
- **No empty agreement or generic praise.** If a reply carries no
  information, it's not worth sending.
- No flattery, no thread-hijacking into self-promotion, no restating the post.
- Don't invent facts, papers, numbers, or experiences the author hasn't had.
  If an angle would need a claim you can't ground, pick a different angle.
- If a post genuinely doesn't warrant a reply, still fill the fields, but say
  so plainly in the report — the rejection call is the author's to make.

Write everything via `notion-update-page` directly, no chat approval first —
review happens in Notion. Leave `Status = New`.

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

One report at the end: how many rows were staged, then the rows ranked most
promising first — for each, the three replies and the retweet suggestion with
a few words on the angle each takes, and which option you'd send. Then the
likely-skips with a one-line reason each, so the author can reject them in
bulk. Flag anything unusual (empty corpus, failed sources, thin signal).
