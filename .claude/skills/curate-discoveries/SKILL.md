---
name: curate-discoveries
description: Find posts worth engaging with and curate them in the Response Calendar, learning from which past posts the author actually commented on versus rejected. Use when the user asks to find posts to engage with, discover new posts, or clean up/prioritise their Response Calendar.
---

# Curate Discoveries

Two halves: a script fetches and stages candidates (deterministic, costs money per
read), then you judge relevance against the author's past behaviour.

**Careful — the Response Calendar has two status properties differing only by case:**
- `Status` (capital) — review workflow: `New`, `Reviewed`, `Stale`,
  `Rejected (irrelevant)`, `Rejected (IDK what to say)`
- `status` (lowercase) — the engagement signal you learn from: `Commented`,
  `Rejected`, `not-commented`

Notion matches names exactly, so mixing them up fails silently. The signal is the
**lowercase** one.

## Fetching new candidates

```bash
.venv/bin/python scripts/discover.py            # add --dry-run to preview
```

Reads `interests.md` for accounts and topics, ranks by engagement, skips anything
already seen or already in the calendar, and writes the top ones with
`Status = New` and `status` empty. Report its output as-is; don't re-rank on
engagement yourself, that's already done.

## Learning the signal

Read existing rows (data source `collection://b64eb9c5-f591-82ff-bdc9-878b128a21aa`):

```sql
SELECT "Original Tweet Text", "status", "Status"
FROM "collection://b64eb9c5-f591-82ff-bdc9-878b128a21aa"
WHERE "status" IS NOT NULL
```

Interpret the lowercase `status`:
- **`Commented`** — the author engaged. **Positive signal**: more like these.
- **`Rejected`** — actively unwanted. **Negative signal**: avoid this kind.
- **`not-commented`** — no reply happened, but the content wasn't bad. **Weak or
  no signal.** Treat it as neutral. Do not read it as rejection — the author may
  simply not have gotten to it.

Infer what distinguishes Commented from Rejected: subject matter, technical depth,
whether there's a real opening to say something substantive, tone, who posted it.
If there are very few of either, say so — thin signal means low-confidence
curation, not a confident call.

## Curating

For each row with `Status = New`:
1. Judge it against the inferred signal.
2. Clearly a Rejected-type post → set `Status = Rejected (irrelevant)`. Leave the
   lowercase `status` alone; that's the author's to set, not yours.
3. Otherwise leave `Status = New` for them to work through.
4. Never set the lowercase `status` — it records what the author actually did, and
   writing it would corrupt the very signal this skill learns from.

Then report: how many were staged, how many you pruned and on what basis, and the
handful you'd start with, most promising first, with a one-line reason each.
