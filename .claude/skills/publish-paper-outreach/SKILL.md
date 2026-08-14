---
name: publish-paper-outreach
description: Send real paper-outreach messages (Gmail/X DM) to every author with a Send Via set in Notion, export LinkedIn authors as CSV lead lists for the founder's LinkedIn automation tool (Linked Helper — sends never run through our code), and check for replies/send scheduled follow-ups on later runs. Use when the user explicitly asks to send/publish paper outreach, or to check outreach replies/follow-ups.
---

# Publish Paper Outreach

Sends real outreach messages on the account's behalf — the actual
send/reply-check logic stays in tested scripts (`gtm_agent/send_outreach.py`,
`gtm_agent/send_followups.py`), not LLM-driven reasoning. This skill is the
trigger: run the script, report back what it did.

This is deliberately separate from `paper-outreach`, which only fetches
authors and drafts messages and never sends — same split as
`discover-and-draft-x-replies`/`publish-x-replies`. `paper-outreach` never touches
`Send Via`; a human picks it by hand in Notion per author (Email/X/LinkedIn),
after reviewing the draft, and that choice alone is the authorization to
reach out — `Selected` is not checked at all.

Requires `NOTION_PAPER_OUTREACH_DB_ID` and `NOTION_PAPER_AUTHORS_DB_ID` in
`.env` — if either is missing, surface that directly rather than guessing an
ID.

## Sending

```bash
.venv/bin/python gtm_agent/send_outreach.py
```

**This step sends real messages** (Gmail/X DM) to every author with a
`Send Via` set in Notion — picking a channel there is itself the human's
authorization for exactly who gets contacted; invoking this skill is
authorization to act on what's staged, same as `publish-x-replies`. Don't
ask for confirmation per author. If nobody has `Send Via` set yet, tell the
user to do that in Notion first (or run `paper-outreach` to draft messages
first if nothing's drafted yet) rather than guessing who they mean.

`Scheduled Time` is an optional additional gate on top of `Send Via`: empty
sends immediately (unchanged default behavior), a future time holds that
author until a later run — report anyone skipped for this reason separately
from anyone skipped for a missing OAuth token or contact. This is a plain
local due-time check, not a Typefully push — Typefully doesn't do DMs, so
Paper Authors sends always go through the direct Gmail/X API regardless of
`Scheduled Time`.

`Send Via` decides what gets used, not just whether: `Email` sends the
Subject + Message together; `X` or `LinkedIn` send the Message only and drop
the Subject entirely. Anyone still missing a Message at this point gets one
drafted first (same drafting logic as `paper-outreach`'s draft step, always
in Email format).

Whatever went wrong on a failed or skipped send (no OAuth token, no contact
on file for that channel, LinkedIn's lack of a send API, an API error) gets
written into the `Post Error` column so the reason is visible directly in
Notion — a later successful send clears it. Report per author: channel,
whether it sent or only drafted (and why, if it only drafted), and the
content for anything that needs manual copy-paste — `Message` (with
`Subject`, for Email) for Email/X, or `LinkedIn Note` for LinkedIn.

`Send Via = LinkedIn` never sends from our code — there's no official
LinkedIn API, and this repo never drives LinkedIn directly (no passwords,
no LinkedIn endpoints; that boundary stands). Instead, LinkedIn sends run
through the founder's LinkedIn automation tool (**Linked Helper** as of
2026-08-14, trialing; the founder keeps invites ≤80/month by choice): a
`LinkedIn Note` (≤200 characters, LinkedIn's cap on connection-request
notes) is drafted separately from `Message`, and

```bash
.venv/bin/python gtm_agent/export_linkedin_leads.py    # add --paper <substring> to filter
```

writes one CSV per paper (profile URL + full name) into `exports/linkedin/`
and prints the note + follow-up drafts to paste into that paper's campaign
sequence in the tool. The human uploads the CSV, launches the campaign
(the tool then owns invite pacing, follow-up chaining, and stop-on-reply),
and flips each author's `Status` to `Sent` in Notion — the tool doesn't
report back to Notion, so that flip is manual and is the only record a
LinkedIn send happened.

## Checking replies / sending follow-ups

```bash
.venv/bin/python gtm_agent/send_followups.py              # add --dry-run to preview
```

Safe to run repeatedly — checks Email/X threads for a reply first (stops
follow-ups permanently on that author if found), otherwise sends the next
scheduled follow-up if enough time has passed (`OUTREACH_FOLLOWUP1_DAYS`/
`OUTREACH_FOLLOWUP2_DAYS` in `.env`, default 6/10 days). Never sends a third
message after Follow-up 2. Report who replied, who got a follow-up, and who's
still waiting on timing. Run this by default when the user just says "check
outreach" with no other signal.

LinkedIn rows are deliberately excluded from this script: their follow-up
timing lives inside the LinkedIn tool's campaign sequence (set up at export
time with the `Followup 1/2 Message` drafts), so drafting or nudging here
too would send people duplicate touches. LinkedIn replies are the user's to
check in the tool/LinkedIn, flipping `Status` to `Replied` by hand.

## Update memory (automatic, every run)

After reporting, run the procedure in `.claude/memory-update-procedure.md`
against whatever this run actually sent or found replied — `memory/outreach-voice.md`
and `memory/outreach-topics.md` are the files it can touch. No user request
needed, and it's a silent no-op when nothing new happened.

## Notes

- If a script exits with a config error (missing `NOTION_API_TOKEN`,
  `OPENAI_API_KEY`, etc.) or says an OAuth token needs
  `gmail_oauth_login.py`/`x_oauth_login.py` re-run, surface that directly —
  don't try to work around it.
- LinkedIn has no send or read API at all — sends go through the founder's
  LinkedIn automation tool (export_linkedin_leads.py), never through this
  repo's code, and follow-ups leaves those rows alone; replies there are
  the user's to check.
- A hand-written `Message`/`Subject` in Notion is always used as-is and
  never overwritten.
