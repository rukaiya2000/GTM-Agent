---
name: draft-replies
description: Draft reply options in the author's voice for posts staged in the Response Calendar, so they can pick one and reply by hand. Use when the user asks to draft replies, write responses to discovered posts, or work through their Response Calendar.
---

# Draft Replies

Fills `Reply 1`, `Reply 2`, `Reply 3` on Response Calendar rows with three
genuinely different reply options in the author's voice. **You never post
anything** — the author picks one and replies on X by hand. That's deliberate:
automated engagement is what gets accounts suspended (`x-req.md` §2.5).

Data source: `collection://b64eb9c5-f591-82ff-bdc9-878b128a21aa`

## Which rows to draft for

Rows where `Status` is `New` or `Reviewed` **and** `Reply 1` is empty. Skip:
- `Status = Stale`, `Rejected (irrelevant)`, `Rejected (IDK what to say)`
- rows where `Self-Written Reply` is already filled — the author handled it
- rows that already have replies, unless asked to redo them

If the user names specific rows, do those instead.

## Voice

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

## Writing the three replies

Each ≤280 characters. They must be **three different angles**, not three
rewordings of the same thought. Useful angles:
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
- If the post genuinely doesn't warrant a reply, say so and suggest the author set
  `Status = Rejected (IDK what to say)` rather than manufacturing three.

## Writing back

Set `Reply 1`, `Reply 2`, `Reply 3` via `notion-update-page`. Do it directly, no
chat approval first — review happens in Notion.

**Never write these:** `Selected`, `Approved`, `Posted`, `Self-Written Reply`, or
the lowercase `status`. They all record what the *author* decided or did, and
writing them would both misrepresent that and corrupt the signal
`curate-discoveries` learns from. (Note `Status` capital-S and `status` lowercase
are two different properties — see below.)

## Reporting

Say how many rows you drafted for, and for each one show the three replies with a
few words on what angle each takes, so the author can choose without opening every
row. Flag any row you skipped and why.

## The two status properties

Differ only by case; Notion matches exactly, so confusing them fails silently.

- `Status` (capital) — workflow: `New`, `Reviewed`, `Stale`, `Rejected (irrelevant)`,
  `Rejected (IDK what to say)`. You may read it; only set it if asked.
- `status` (lowercase) — the author's engagement record: `Commented`, `Rejected`,
  `not-commented`. **Never write it.**
