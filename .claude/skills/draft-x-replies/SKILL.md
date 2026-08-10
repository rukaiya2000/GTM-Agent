---
name: draft-x-replies
description: One pass over the engagement pipeline — discover posts worth engaging with, curate them in the Response Calendar by learning from which past posts the author actually commented on versus rejected, then draft three reply options in the author's voice for the most promising rows. Use when the user asks to find posts to engage with, discover new posts, clean up or prioritise their Response Calendar, draft replies, or work through discovered posts.
---

# Draft X Replies

One skill, three phases: **fetch** candidates (deterministic script, costs money
per read), **curate** them against the author's past behaviour, then **draft**
replies for the rows worth their time. **You never post anything** — the author
picks a reply and sends it on X by hand. That's deliberate: automated engagement
is what gets accounts suspended (`x-req.md` §2.5).

Not every invocation runs all three phases. "Find posts" → phases 1–3. "Clean up
my calendar" → 2 only. "Draft replies" → 3 only (plus 2's signal-reading to pick
rows). Skip what the user didn't ask for; fetching costs money.

Database: `ec8eb9c5f591820393d101733079983f` (Response Calendar — the single
source of truth, on the GTM page). Fetch it first: the response names its
`collection://…` data source id, which the SQL below needs. **If the fetch
404s, the Notion connector is attached to the wrong workspace** — tell the
user to point Claude's Notion connection at the workspace holding the GTM
page; do not guess at a different database.

Two properties carry the workflow and the signal — don't confuse them:

- `Status` (select) — review workflow: `New`, `Reviewed`, `Ready to post`,
  `Stale`, `Rejected (irrelevant)`, `Rejected (IDK what to say)`. You may read
  it and set it while curating.
- `Posted` (checkbox) — the engagement signal you learn from: the author ticks
  it when they actually sent a reply to that post. **Never write it.** It
  records what the author did; writing it corrupts the very signal this skill
  learns from.

Other fields: `Reply 1/2/3` (your three options), `Draft` (the final message
to post), `Selected` (which option they picked), `Approved`/`Keep?`/
`Self-Written Reply` (the author's), `Source` (`discovery` or `mention` —
mentions warrant a faster response), `Added Date` (when the row entered the
calendar), `Original Tweet Date` (when the post was tweeted — use it for the
staleness call).

## Phase 1 — Fetch new candidates

```bash
.venv/bin/python scripts/discover.py            # add --dry-run to preview
```

Reads `interests.md` for accounts and topics, ranks by engagement, skips anything
already seen or already in the calendar, and writes the top ones with
`Status = New` and `status` empty. Report its output as-is; don't re-rank on
engagement yourself, that's already done.

## Phase 2 — Curate: standing criteria first, learned signal second

### The author's standing criteria

You are evaluating tweets for a founder/operator workflow. **Be selective.**
Keep a tweet only if it is:

1. Announcing a new RL environment
2. A new paper or post on autonomously scaling agent evaluations, benchmarks,
   or RL environments
3. Data methods related to scaling post-training agents
4. A well-thought-out opinion on scaling post-training, RL, or
   data/environments for post-training
5. Automatic harness engineering / auto-optimization for AI systems
6. Recent enough to still be worth engaging — too old to reply to now goes to
   `Status = Stale`, not Rejected

Focus on benchmarks and environments related to:
- computer/browser use agents
- tool use capabilities in enterprise workflows
- long-horizon agentic capabilities

Reject tweets that are: promotional, engagement bait, meme content, shallow
commentary, generic hype, low-information reposting, or robotics-hardware
related.

### The learned signal

The criteria above are the baseline; the author's actual behaviour shows how
they apply them in practice. Read existing rows, substituting the data source
id from the database fetch:

```sql
SELECT "Original Tweet Text", "Posted", "Keep?", "Status"
FROM "collection://<data source id from the fetch>"
WHERE "Posted" = '__YES__' OR "Keep?" = '__YES__' OR "Status" LIKE 'Rejected%'
```

Interpret:
- **`Posted` ticked** — the author actually replied. **Positive signal**: more
  like these.
- **`Keep?` ticked** — judged worth keeping even without a reply yet. Weaker
  positive.
- **`Status = Rejected (…)`** — actively unwanted. **Negative signal**: avoid this kind.
- **Everything else** — no reply happened, but the content wasn't necessarily
  bad. **Weak or no signal.** Treat it as neutral, not as rejection — the author
  may simply not have gotten to it.

Infer what distinguishes Commented from Rejected: subject matter, technical depth,
whether there's a real opening to say something substantive, tone, who posted it.
If there are very few of either, say so — thin signal means low-confidence
curation, not a confident call.

Then, for each row with `Status = New`:
1. Judge it against the inferred signal.
2. Clearly a Rejected-type post → set `Status = Rejected (irrelevant)`. Leave the
   lowercase `status` alone.
3. Otherwise leave `Status = New`.

Finish the phase with a shortlist: the rows you'd start with, most promising
first, with a one-line reason each.

## Phase 3 — Draft replies for the shortlist

Draft for the shortlist from phase 2 — **up to ~8 rows unless the user asks for
more or names specific rows**. Drafting for every surviving row wastes tokens on
posts the author may never get to; the rest stay staged and can be drafted later.

Eligible rows: `Status` is `New` or `Reviewed` **and** `Reply 1` is empty. Skip:
- `Status = Stale`, `Rejected (irrelevant)`, `Rejected (IDK what to say)`
- rows where `Self-Written Reply` is already filled — the author handled it
- rows that already have replies, unless asked to redo them

### Voice

Read the **`tweets`** bucket of `voice_corpus.json` — replies are short-form, so
the `articles` bucket is not relevant here. Entries with `post_type: "reply"` are
replies the author actually sent (via `scripts/sync_replies.py`) — weight those
highest, they're the closest match to what you're writing. Entries carrying a
`metrics.engagement_rate` are measured performers; prefer higher ones, but treat
a missing metric as unmeasured, never as bad. Match the author's tone, vocabulary,
technical depth, and punctuation habits. If the file is missing or empty, say so
and write plainly rather than inventing a voice.

A reply is not a broadcast post. Same voice, different register: it's responsive
and conversational, it assumes the original post as context, and it doesn't
re-introduce what the reader can already see.

### Writing the three replies

Fill `Reply 1`, `Reply 2`, `Reply 3`. The author's standing direction for this
workflow — where it conflicts with a corpus habit, this direction wins:

- technical and peer-level, in a founder/executive voice
- concise: **max 220 characters and 1–2 sentences each** (deliberately tighter
  than X's 280 limit)
- curious or additive — the goal is to engage researchers/builders and start a
  thoughtful conversation
- not salesy; don't mention the company unless directly relevant
- no emojis, no bulleting
- no jargon overload unless the tweet itself is highly technical
- sound natural on X, not like a memo

They must be **three different angles**, not three rewordings of the same
thought. Useful angles:
- add a concrete detail, example, or counter-example the post didn't cover
- share directly relevant first-hand experience
- ask a specific, genuine question that moves the thread forward
- respectfully complicate or push back on a claim
- connect it to adjacent work the author knows about

Hard rules:
- **No empty agreement or generic praise.** "Great point", "So true", "This 👏" —
  never. If a reply carries no information, it's not a reply worth sending.
- No flattery, no thread-hijacking into self-promotion, no restating the post.
- No hashtags.
- Don't invent facts, papers, numbers, or experiences the author hasn't had. If an
  angle would need a claim you can't ground, pick a different angle.
- If a shortlisted post genuinely doesn't warrant a reply, say so and suggest the
  author set `Status = Rejected (IDK what to say)` rather than manufacturing three.

### Writing back

Set `Reply 1`, `Reply 2`, `Reply 3` via `notion-update-page`, and put the
strongest of the three into `Draft` as the proposed final message. Do it
directly, no chat approval first — review happens in Notion.

`Status = Ready to post` is the author's call, not yours: they flip it (or ask
you to) once they're happy with `Draft`. When they ask you to stage a row —
"stage this one", "use reply 2" — copy their chosen or edited reply into
`Draft` and set `Status = Ready to post` then.

**Never write these:** `Selected`, `Approved`, `Posted`, `Keep?`, or
`Self-Written Reply`. They all record what the *author* decided or did.

## Reporting

One report at the end, not one per phase: how many rows were staged, how many you
pruned and on what basis, then each drafted row's three replies with a few words
on what angle each takes — so the author can choose without opening every row.
Flag anything you skipped and why, including shortlisted rows left undrafted.
