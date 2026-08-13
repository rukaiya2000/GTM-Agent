---
name: publish-paper-outreach
description: Send real paper-outreach messages (Gmail/X DM) to every author with a Send Via set in Notion, and check for replies/send scheduled follow-ups on later runs. Use when the user explicitly asks to send/publish paper outreach, or to check outreach replies/follow-ups.
---

# Publish Paper Outreach

Sends real outreach messages on the account's behalf — the actual
send/reply-check logic stays in tested scripts (`gtm_agent/send_outreach.py`,
`gtm_agent/send_followups.py`), not LLM-driven reasoning. This skill is the
trigger: run the script, report back what it did.

This is deliberately separate from `paper-outreach`, which only fetches
authors and drafts messages and never sends — same split as
`draft-x-replies`/`publish-x-replies`. `paper-outreach` never touches
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
message text (with Subject, for Email) for anything that needs manual
copy-paste.

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
- LinkedIn has no send or read API at all — those rows always draft-only,
  and follow-ups leaves them alone; replies there are the user's to check.
- A hand-written `Message`/`Subject` in Notion is always used as-is and
  never overwritten.
