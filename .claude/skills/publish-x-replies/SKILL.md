---
name: publish-x-replies
description: Push every "Ready to post" reply row in the Response Calendar Notion database to Typefully for scheduled publishing (marking it "Scheduled"), post any due retweet/quote-retweet directly, and reconcile previously-scheduled Typefully drafts. Use when the user asks to post their staged replies, send their engagement queue, or run the reply-posting worker.
---

# Publish X Replies

Posts real replies and retweets to X on the account's behalf — the actual
posting logic stays in tested code (`gtm_agent/post_response_calendar.py` +
`gtm_agent/sync_typefully_status.py`), not LLM-driven reasoning. This skill
is the trigger: run both scripts, report back what they did.

This is deliberately separate from `discover-and-draft-x-replies`, which never posts, and
from `publish-x-queue`, which only knows the Tweet Drafts schema. A row only
gets here because the author (or the AI assistant, on the author's explicit request)
set `Selected`, `Scheduled Time`, and `Status = Ready to post` in the
Response Calendar — this skill automates firing the already-decided action
at the already-decided time, nothing more.

## Steps

1. Run, from the project root:

   ```bash
   .venv/bin/python gtm_agent/post_response_calendar.py
   ```

2. Then run the reconciliation pass, which checks previously-pushed Typefully
   drafts and flips them to `Posted` once Typefully has actually published them:

   ```bash
   .venv/bin/python gtm_agent/sync_typefully_status.py
   ```

3. Report both scripts' output back to the user plainly — what got pushed to
   Typefully, what posted directly (with links), what resolved as published,
   what failed and why. Don't editorialize or repeat information the output
   already states clearly.

## What the scripts do (for context, not to be reimplemented here)

**`post_response_calendar.py`** — fetches all Response Calendar rows with
`Status = Ready to post`. `Selected` decides the path:
- `Reply 1/2/3` or `Self-Written Reply` with no `Typefully Draft ID` yet are
  pushed to Typefully immediately as a reply (`reply_to_url` = the original
  tweet), not gated on `Scheduled Time` locally — Typefully owns that gate
  from here via its own `publish_at`. On a successful push, `Status` is set
  to `Scheduled` and the returned draft id is written to `Typefully Draft ID`.
- `Retweet` rows are unaffected by Typefully (no confirmed retweet-an-
  arbitrary-tweet endpoint there) — still filtered to ones whose
  `Scheduled Time` has passed, and posted directly: `Retweet Message` filled
  in quote-retweets with that text; empty does a plain retweet, no text.
  There is no `Like` action — it was cut deliberately (see Notes).
- On direct-post success: sets `Status = Posted` and appends the quote text
  to `voice_corpus.json` (plain retweets carry no text, so nothing to learn
  from — nothing is appended for those).
- On failure (either path): writes the error to `Post Error`, leaves
  `Status` alone (so it's retried on the next invocation), and keeps going
  rather than aborting the whole batch.

**`sync_typefully_status.py`** — for every row with a `Typefully Draft ID`
still at `Status = Scheduled`, checks its status via the Typefully API:
- `published` → sets `Status = Posted` and appends the reply text to
  `voice_corpus.json`.
- `error` → writes the error to `Post Error`, leaves `Status` alone for
  manual retry.
- anything else (`draft`/`scheduled`/`planned`/`publishing`) → still
  pending, no change; check again on a later run.

Unlike `publish-x-queue`, there's no multi-step partial-failure case to worry
about — each row is a single API call, so a failure never leaves a
partially-posted thread or an orphaned draft behind.

## Update memory (automatic, every run)

After reporting, run the procedure in `.claude/memory-update-procedure.md`
against whatever this run actually posted or rejected — `memory/x-voice.md`
and `memory/x-topics.md` are the files it can touch. No user request
needed, and it's a silent no-op when nothing was due.

## Notes

- If the script exits with a config error (missing `NOTION_API_TOKEN`,
  `X_CLIENT_ID`, etc.), or says the X OAuth token needs
  `gtm_agent/x_oauth_login.py` re-run, surface that directly — don't try to
  work around it.
- **No `Like` action exists on purpose.** The project's own PRD
  (`Req/x-req.md`) flags auto-like as the specific pattern that gets X
  accounts suspended, and it carries no authored text to justify automating
  — `Like` was removed from the Response Calendar's `Selected` options
  entirely. If asked to add it back, flag that tradeoff rather than just
  implementing it.
- Invoking this skill is itself the user's authorization to post whatever is
  due — don't ask for confirmation per row. If they didn't mean to trigger
  it, that's what `Scheduled Time` already guards against: nothing posts
  unless a row was explicitly staged with a due time.
