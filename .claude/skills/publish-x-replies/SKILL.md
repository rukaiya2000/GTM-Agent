---
name: publish-x-replies
description: Post every "Ready to post" row in the Response Calendar Notion database whose Scheduled Time has passed — the chosen reply, or a plain/quote retweet. Use when the user asks to post their staged replies, send their engagement queue, or run the reply-posting worker.
---

# Publish X Replies

Posts real replies and retweets to X on the account's behalf — the actual
posting logic stays in tested code (`scripts/post_response_calendar.py`),
not LLM-driven reasoning. This skill is the trigger: run the script, report
back what it did.

This is deliberately separate from `draft-x-replies`, which never posts, and
from `publish-x-queue`, which only knows the Tweet Drafts schema. A row only
gets here because the author (or Claude, on the author's explicit request)
set `Selected`, `Scheduled Time`, and `Status = Ready to post` in the
Response Calendar — this skill automates firing the already-decided action
at the already-decided time, nothing more.

## Steps

1. Run, from the project root:

   ```bash
   .venv/bin/python scripts/post_response_calendar.py
   ```

2. Report the script's output back to the user plainly — how many rows were
   due, what got posted (with links), what failed and why. Don't editorialize
   or repeat information the output already states clearly.

## What the script does (for context, not to be reimplemented here)

- Fetches all Response Calendar rows with `Status = Ready to post`.
- Filters to ones whose `Scheduled Time` is already in the past — a row with
  no `Scheduled Time`, or one still in the future, is left untouched.
- Posts each due row, one at a time, oldest-scheduled first, with a short
  pause between posts. `Selected` decides the action:
  - `Reply 1/2/3` or `Self-Written Reply` → posts that text as a reply to the
    original tweet.
  - `Retweet` with `Retweet Message` filled in → quote-retweets with that
    text.
  - `Retweet` with `Retweet Message` empty → a plain retweet, no text.
  - There is no `Like` action — it was cut deliberately (see Notes).
- On success: sets `Status = Posted` and appends the reply/quote text to
  `voice_corpus.json` (plain retweets carry no text, so nothing to learn
  from — nothing is appended for those).
- On failure: writes the error to `Post Error`, leaves `Status` alone (so
  it's retried on the next invocation), and keeps going to the next due row
  rather than aborting the whole batch.

Unlike `publish-x-queue`, there's no multi-step partial-failure case to worry
about — each row is a single API call, so a failure never leaves a
partially-posted thread or an orphaned draft behind.

## Notes

- If the script exits with a config error (missing `NOTION_API_TOKEN`,
  `X_CLIENT_ID`, etc.), or says the X OAuth token needs
  `scripts/x_oauth_login.py` re-run, surface that directly — don't try to
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
