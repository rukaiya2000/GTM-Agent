---
name: paper-outreach
description: Fetch a staged paper's authors, web-research missing contact handles, and draft Email/X outreach messages (Subject + Message) plus a 200-char LinkedIn connection-request note for every author — all in one pass, no manual Notion setup required first. Never sends anything; see publish-paper-outreach for that. Use when the user asks to run paper outreach, fetch paper authors, or draft outreach for a paper.
---

# Paper Outreach

A separate, Notion-only pipeline for reaching out to research paper authors —
distinct from the X pipelines, no shared voice corpus or review-gate
machinery. All logic lives in tested scripts (`gtm_agent/fetch_paper_authors.py`,
`gtm_agent/research_authors.py`, `gtm_agent/send_outreach.py`); this skill is the
trigger, not the reasoning. See `Req/paper-outreach.md` for the original
feature idea and the README's "Pipeline 3: Paper outreach" section for full
setup docs.

This skill only drafts — it never sends. Sending real messages and checking
for replies/follow-ups is a deliberately separate skill, `publish-paper-outreach`,
same split as `draft-x-replies`/`publish-x-replies`. If the user asks to
actually send/publish outreach or check replies, use that skill instead.

Two Notion databases: **Paper Outreach** (one row per paper) and **Paper
Authors** (one row per author, related to a paper). `NOTION_PAPER_OUTREACH_DB_ID`
and `NOTION_PAPER_AUTHORS_DB_ID` must be set in `.env` — if either is missing,
surface that directly rather than guessing an ID.

Before drafting, check `memory/outreach-voice.md` and
`memory/outreach-topics.md` (repo root) — observed tone and topic signal
from real staged papers and sent/replied messages, with a stated confidence
level. Both currently have very little to draw on; when they say so, draft
from the script defaults and `memory/x-voice.md` instead of guessing a tone.

## Default flow: run everything in one pass

When the user asks to run paper outreach on a newly staged paper (or just
says "run paper outreach" with no other signal), run Steps 1 → 2 → 3 below
back to back, without stopping in between and without waiting for anything
to be set by hand in Notion first. That's the whole point of this skill: one
invocation takes a paper from just a link to every author having a drafted
Subject + Message, with contact handles filled in as best as automated
research can get them, ready for the user to review before `publish-paper-outreach`
ever runs.

## Step 1 — Resolve authors + draft blurb

```bash
yes "" | .venv/bin/python gtm_agent/fetch_paper_authors.py
```

The script prompts interactively per paper ("Also fetch anyone by name?") —
piping `yes ""` answers every prompt with Enter (fetch only the top 5,
correspondence-prioritized), which is the right default for an unattended
run. If the user names specific extra co-authors to include, fetch everyone
instead and pick the ones they named out of the report:

```bash
.venv/bin/python gtm_agent/fetch_paper_authors.py --all-authors
```

Requires a paper already staged in the **Paper Outreach** database (a `Paper
link` is enough — `Paper Name` gets backfilled from the resolved title if
left blank) — that row is added by hand in Notion, not by this skill. If
asked to add one, use the Notion tools to create it directly (title = paper
name if known, `Paper link` = url/arXiv id, `Notes` = anything the user
wants folded into the blurb tone) rather than editing scripts. A blank
`Paper Name` also means the `Paper` relation column shows blank on every
linked Paper Authors row until this step backfills it.

Report per-paper: how many authors were staged, how many landed
`Draft Ready` (confirmed email/handle) vs `Needs Handles`, and the generated
Blurb. Needs `OPENAI_API_KEY`.

## Step 2 — Web-research missing handles

```bash
.venv/bin/python gtm_agent/research_authors.py            # add --dry-run to preview
```

Part of the default flow, not an optional extra — run it right after Step 1
so as many authors as possible have a contact for Step 3 to draft against.
Spawns one lightweight subagent per `Needs Handles` author to search the open web
(or, if subagents aren't available, research each one sequentially yourself);
findings move rows to `Needs Review` (never straight to `Draft Ready` — a web
match is a candidate, not a confirmation) with cited evidence. Needs
`uv sync --extra research`. Report what was found per author and flag
anyone still `Needs Handles` after the pass — those get skipped in Step 3
since there's no contact to draft against.

## Step 3 — Draft messages (never sends)

```bash
.venv/bin/python gtm_agent/send_outreach.py --draft-only
```

Drafts a `Subject` + `Message` for every author who doesn't have one yet and
has *some* contact info on file (Email, X Handle, or LinkedIn) — always in
Email format (subject + body), regardless of what contact info they actually
have. Anyone with a LinkedIn URL on file additionally gets a `LinkedIn Note`
drafted — a separate field, capped at 200 characters (LinkedIn's own limit
on connection-request notes), not a rename or reuse of `Message`. This skill
never touches `Send Via` at all — that's entirely the human's decision, made
afterward in Notion. A hand-written `Message`, `Subject`, or `LinkedIn Note`
is always used as-is and never overwritten. **This never sends anything** —
Status lands on `Message Drafted`, ready for the user to review.

Report per author: the drafted Subject + Message (and LinkedIn Note, if
drafted), and anyone skipped for having no contact info at all on file
(nothing to ever send it through, regardless of channel).

When Step 3 is done, tell the user the drafts are ready for review in Notion
— they still need to pick `Send Via` per author themselves — and that
`publish-paper-outreach` is the separate skill to run when they're ready to
actually send. Don't run it yourself as part of this flow, and don't set
`Send Via` on their behalf.

## Update memory (automatic, every run)

After reporting, run the procedure in `.claude/memory-update-procedure.md`
against any newly staged paper's blurb — `memory/outreach-topics.md` is the
file it can touch (this skill never sends, so `outreach-voice.md` won't
change here). No user request needed, and it's a silent no-op when nothing
new was staged.

## Notes

- If a script exits with a config error (missing `NOTION_API_TOKEN`,
  `OPENAI_API_KEY`, etc.), surface that directly — don't try to work around
  it.
- A hand-written `Message`, `Subject`, or `LinkedIn Note` in Notion is always
  used as-is and never overwritten by Step 3.
- This skill never touches Gmail/X OAuth or sends anything — that's entirely
  `publish-paper-outreach`'s job.
