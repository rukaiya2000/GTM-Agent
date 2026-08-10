---
name: discover-and-draft
description: One pass over the engagement pipeline — discover posts worth engaging with, curate them in the Response Calendar by learning from which past posts the author actually commented on versus rejected, then draft three reply options in the author's voice for the most promising rows. Use when the user asks to find posts to engage with, discover new posts, clean up or prioritise their Response Calendar, draft replies, or work through discovered posts.
---

# Discover and Draft

One skill, three phases: **fetch** candidates (deterministic script, costs money
per read), **curate** them against the author's past behaviour, then **draft**
replies for the rows worth their time. **You never post anything** — the author
picks a reply and sends it on X by hand. That's deliberate: automated engagement
is what gets accounts suspended (`x-req.md` §2.5).

Not every invocation runs all three phases. "Find posts" → phases 1–3. "Clean up
my calendar" → 2 only. "Draft replies" → 3 only (plus 2's signal-reading to pick
rows). Skip what the user didn't ask for; fetching costs money.

Data source: `collection://b64eb9c5-f591-82ff-bdc9-878b128a21aa`

**Careful — the Response Calendar has two status properties differing only by
case.** Notion matches names exactly, so mixing them up fails silently:

- `Status` (capital) — review workflow: `New`, `Reviewed`, `Stale`,
  `Rejected (irrelevant)`, `Rejected (IDK what to say)`. You may read it and set
  it while curating.
- `status` (lowercase) — the engagement signal you learn from: `Commented`,
  `Rejected`, `not-commented`. **Never write it.** It records what the author
  actually did; writing it corrupts the very signal this skill learns from.

## Phase 1 — Fetch new candidates

```bash
.venv/bin/python scripts/discover.py            # add --dry-run to preview
```

Reads `interests.md` for accounts and topics, ranks by engagement, skips anything
already seen or already in the calendar, and writes the top ones with
`Status = New` and `status` empty. Report its output as-is; don't re-rank on
engagement yourself, that's already done.

## Phase 2 — Learn the signal, then curate

Read existing rows:

```sql
SELECT "Original Tweet Text", "status", "Status"
FROM "collection://b64eb9c5-f591-82ff-bdc9-878b128a21aa"
WHERE "status" IS NOT NULL
```

Interpret the lowercase `status`:
- **`Commented`** — the author engaged. **Positive signal**: more like these.
- **`Rejected`** — actively unwanted. **Negative signal**: avoid this kind.
- **`not-commented`** — no reply happened, but the content wasn't bad. **Weak or
  no signal.** Treat it as neutral, not as rejection — the author may simply not
  have gotten to it.

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

Fill `Reply 1`, `Reply 2`, `Reply 3`, each ≤280 characters. They must be **three
different angles**, not three rewordings of the same thought. Useful angles:
- add a concrete detail, example, or counter-example the post didn't cover
- share directly relevant first-hand experience
- ask a specific, genuine question that moves the thread forward
- respectfully complicate or push back on a claim
- connect it to adjacent work the author knows about

Hard rules:
- **No empty agreement.** "Great point", "So true", "This 👏" — never. If a reply
  carries no information, it's not a reply worth sending.
- No flattery, no thread-hijacking into self-promotion, no restating the post.
- Only use emoji/hashtags if the corpus shows the author actually does.
- Don't invent facts, papers, numbers, or experiences the author hasn't had. If an
  angle would need a claim you can't ground, pick a different angle.
- If a shortlisted post genuinely doesn't warrant a reply, say so and suggest the
  author set `Status = Rejected (IDK what to say)` rather than manufacturing three.

### Writing back

Set `Reply 1`, `Reply 2`, `Reply 3` via `notion-update-page`. Do it directly, no
chat approval first — review happens in Notion.

**Never write these:** `Selected`, `Approved`, `Posted`, `Self-Written Reply`, or
the lowercase `status`. They all record what the *author* decided or did.

## Reporting

One report at the end, not one per phase: how many rows were staged, how many you
pruned and on what basis, then each drafted row's three replies with a few words
on what angle each takes — so the author can choose without opening every row.
Flag anything you skipped and why, including shortlisted rows left undrafted.
