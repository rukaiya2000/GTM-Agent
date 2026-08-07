---
name: post-ready-tweets
description: Post every "Ready to post" row in the Tweet Drafts Notion database whose Scheduled Time has passed. Use when the user asks to post their ready tweets, publish everything that's due, or run the posting worker.
---

# Post Ready Tweets

Posts real tweets to X and costs real money per post — the actual posting logic
stays in tested code (`scripts/post_all_due.py`), not LLM-driven reasoning. This
skill is the trigger: run the script, report back what it did.

## Steps

1. Run, from the project root:

   ```bash
   .venv/bin/python scripts/post_all_due.py
   ```

2. Report the script's output back to the user plainly — how many rows were due,
   what got posted (with links), what failed and why. Don't editorialize or repeat
   information the output already states clearly.

## What the script does (for context, not to be reimplemented here)

- Fetches all `Tweet Drafts` rows with `Stage = Ready to post`.
- Filters to ones whose `Scheduled Time` is already in the past — a row with no
  `Scheduled Time`, or one still in the future, is left untouched.
- Posts each due row, one at a time, oldest-scheduled first, with a short pause
  between posts. `single-thread` posts as one tweet; `multi-thread` posts as a
  reply-chained thread (split on `---` separators in `Final Text`); `article`
  publishes a long-form Article via `POST /2/articles/draft` + `/publish`, using
  the `Title` property as the headline and `Final Text` as the body (falling back
  to the first line of `Final Text` if `Title` is empty). Needs X Premium.
- On success: sets `Stage = Posted` and appends the post to `voice_corpus.json`.
- On failure: writes the error to `Post Error`, leaves `Stage` alone (so it's
  retried on the next invocation), and keeps going to the next due row rather than
  aborting the whole batch.

**Two partial-failure cases matter and must not be downplayed** — both leave state
on X, and neither auto-retries because retrying would make it worse:
- A **thread** that fails partway: earlier tweets are live on X, not rolled back.
  The error carries their IDs. Retrying would duplicate the successful prefix.
- An **article** whose draft was created but failed to publish: the draft exists on
  X. The error carries the draft id. Retrying would create a second draft.

If either happens, surface it plainly with the IDs — it needs manual cleanup.

## Notes

- If the script exits with a config error (missing `NOTION_API_TOKEN`, `X_CLIENT_ID`,
  etc.), or says the X OAuth token needs `scripts/x_oauth_login.py` re-run, surface
  that directly — don't try to work around it.
- Invoking this skill is itself the user's authorization to post whatever is due —
  don't ask for confirmation per tweet. If they didn't mean to trigger it, that's
  what "Scheduled Time" already guards against: nothing posts unless they explicitly
  set a due time on it beforehand.
