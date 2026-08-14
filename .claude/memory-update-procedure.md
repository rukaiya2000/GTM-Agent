# Memory update procedure

Not a skill — there's nothing to invoke here. Every skill that touches the
Response Calendar, Tweet Drafts, Paper Authors, or Paper Outreach runs this
procedure itself as its **last step, automatically, every run** — no user
request needed. This file is the one shared definition so those skills don't
each restate it.

`memory/*.md` is evidence-based, not hand-authored opinion. Every claim in
it must trace back to something real: a `Posted` row, a `Rejected (...)`
row, an actual sent/replied outreach message, `voice_corpus.json` content,
or `interests.md` config. Never invent a pattern to fill a file out — thin
history gets reported as thin history, same as `discover-and-draft-x-replies` already
does in its own Phase 3.

## Step 1 — Gather real evidence

Pull current state directly rather than relying on stale numbers from last
time — but only what's relevant to the skill that just ran (a
`publish-x-replies` run only needs the Response Calendar's new
`Posted`/`Rejected` rows, not a full re-fetch of Paper Authors):

- **Response Calendar** (`ec8eb9c5f591820393d101733079983f`): rows where
  `Status = Posted` (positive X-reply signal) or `Status` starts with
  `Rejected` (negative signal). Read what was actually selected/posted, not
  just the count.
- **Tweet Drafts** (`NOTION_TWEET_DRAFTS_DB_ID`): rows where `Stage =
  Posted`.
- **`voice_corpus.json`** (repo root): any entries added by this run,
  including `metrics.engagement_rate` where populated.
- **Paper Authors** (`NOTION_PAPER_AUTHORS_DB_ID`): rows where `Status` is
  `Sent`, `Approved`, or indicates a reply — read the actual `Message`/
  `Subject` text where present.
- **Paper Outreach** (`NOTION_PAPER_OUTREACH_DB_ID`): staged papers and
  their blurbs — topic signal even before outreach starts.
- **`interests.md`** (repo root): enabled/disabled accounts and topics.

If a fetch 404s or a DB id is missing from `.env`, surface that directly and
skip this step — don't let it block the skill's own primary report.

## Step 2 — Decide if anything actually changed

Read the existing `memory/*.md` first. Compare: did this run produce any row
that's new evidence (a fresh `Posted`, `Rejected (...)`, `Sent`, or reply)
compared to what the file already claims?

- **No new evidence** → stop here, write nothing. This is the common case
  on most runs — don't rewrite prose that would just restate the same
  thing, and don't mention it in the skill's report; silent no-op.
- **New evidence exists** → continue to Step 3, and only rewrite the
  specific file(s) that new evidence actually bears on.

## Step 3 — Update the file(s)

Update `memory/x-voice.md`, `memory/x-topics.md`, `memory/outreach-voice.md`,
`memory/outreach-topics.md`, and/or `memory/preferences.md` — whichever the
new evidence is actually about — plus `memory/MEMORY.md`'s confidence table
and "Last generated" line.

**Preserve every file's `## Founder notes (manual — preserved on
regeneration)` section verbatim** — read it before rewriting the file, then
paste it back unchanged at the end. That section is the founder's own direct
input (see `CLAUDE.md`) and this procedure never overwrites it.

Keep the structure each file already has (confidence line up top,
evidence-grounded sections, an explicit "what this is NOT evidence for"
callout where history is thin). Cite the actual source per claim (a specific
row, a specific corpus entry) rather than writing generically. Bump a file's
confidence level only when the new sample meaningfully changes it.

## Step 4 — Mention it, briefly

If a file was rewritten, add one line to the skill's own report — e.g. "memory/x-voice.md updated: +1 posted reply." Don't give this its own separate report section; it's a footnote to whatever the skill was actually doing.

## Notes

- Only ever writes to `memory/`. Never touches `Status` or any other Notion
  field, and never posts or sends anything.
- This is intentionally cheap to skip: on a run with no new signal, Steps 1-2
  are a quick check, not a full resynthesis.
