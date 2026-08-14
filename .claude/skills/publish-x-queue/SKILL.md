---
name: publish-x-queue
description: Push every "Ready to post" single-thread/multi-thread row in the Tweet Drafts Notion database to Typefully for scheduled publishing (marking it "Scheduled"), post any due article directly, and reconcile previously-scheduled Typefully drafts. Use when the user asks to post their ready tweets, publish everything that's due, or run the posting worker.
---

# Publish X Queue

Posts real tweets to X and costs real money per post — the actual posting logic
stays in tested code (`gtm_agent/post_all_due.py` + `gtm_agent/sync_typefully_status.py`),
not LLM-driven reasoning. This skill is the trigger: run both scripts, report
back what they did.

## Steps

1. Run, from the project root:

   ```bash
   .venv/bin/python gtm_agent/post_all_due.py
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

**`post_all_due.py`** — fetches all `Tweet Drafts` rows with `Stage = Ready to post`:
- `single-thread`/`multi-thread` rows with no `Typefully Draft ID` yet are pushed to
  Typefully immediately (not gated on `Scheduled Time` locally — Typefully owns that
  gate from here via its own `publish_at`). On a successful push, `Stage` is set to
  `Scheduled` and the returned draft id is written to `Typefully Draft ID`.
- `article` rows are unaffected by Typefully (not a supported format there) —
  still filtered to ones whose `Scheduled Time` has passed, and published
  directly via `POST /2/articles/draft` + `/publish`, using the `Title` property
  as the headline and `Final Text` as the body (falling back to the first line
  of `Final Text` if `Title` is empty). Needs X Premium.
- On article success: sets `Stage = Posted` and appends the post to `voice_corpus.json`.
- On failure (either path): writes the error to `Post Error`, leaves `Stage`
  alone (so it's retried on the next invocation), and keeps going rather than
  aborting the whole batch.

**`sync_typefully_status.py`** — for every row with a `Typefully Draft ID` still
at `Stage = Scheduled`, checks its status via the Typefully API:
- `published` → sets `Stage = Posted` and appends the post to `voice_corpus.json`.
- `error` → writes the error to `Post Error`, leaves `Stage` alone for manual retry.
- anything else (`draft`/`scheduled`/`planned`/`publishing`) → still pending, no
  change; check again on a later run.

**Two partial-failure cases matter and must not be downplayed** — both leave state
on X, and neither auto-retries because retrying would make it worse:
- A **thread** that fails partway: earlier tweets are live on X, not rolled back.
  The error carries their IDs. Retrying would duplicate the successful prefix.
- An **article** whose draft was created but failed to publish: the draft exists on
  X. The error carries the draft id. Retrying would create a second draft.

If either happens, surface it plainly with the IDs — it needs manual cleanup.

## Update memory (automatic, every run)

After reporting, run the procedure in `.claude/memory-update-procedure.md`
against whatever this run actually posted — `memory/x-voice.md` is the file
it can touch. No user request needed, and it's a silent no-op when nothing
was due.

## Notes

- If the script exits with a config error (missing `NOTION_API_TOKEN`, `X_CLIENT_ID`,
  etc.), or says the X OAuth token needs `gtm_agent/x_oauth_login.py` re-run, surface
  that directly — don't try to work around it.
- Invoking this skill is itself the user's authorization to post whatever is due —
  don't ask for confirmation per tweet. If they didn't mean to trigger it, that's
  what "Scheduled Time" already guards against: nothing posts unless they explicitly
  set a due time on it beforehand.
