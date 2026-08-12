"""Feed replies you actually sent into the voice corpus.

A reply you chose and posted is as much your voice as an original post, but it
only lives in Notion. This copies it into voice_corpus.json so
draft-x-replies and polish-x-drafts can learn from it.

Reads rows with `Status = Posted` where `Selected` names something with text:
a reply field (learned as post_type "reply") or a quote-retweet's
`Retweet Message` (learned as post_type "quote"). Plain retweets (empty
`Retweet Message`) are skipped — there's no text to learn from. This is a
backfill for anything posted outside `scripts/post_response_calendar.py`
(which already writes to the corpus at post time) — e.g. rows posted by hand.
"""

from gtm_agent.config import ConfigError, get_response_calendar_db_id
from gtm_agent.notion_client import NotionApiError, NotionClient
from gtm_agent.voice_corpus import CORPUS_PATH, append_tweet

# Replies are posted by hand, so there's no tweet id to key on. The Notion page
# id is the stable identifier, namespaced so it can't collide with a real one.
NOTION_ID_PREFIX = "notion:"


def main() -> int:
    try:
        db_id = get_response_calendar_db_id()
        notion = NotionClient()
    except ConfigError as e:
        print(f"Config error: {e}")
        return 1

    try:
        rows = notion.get_response_calendar_rows(db_id)
    except NotionApiError as e:
        print(f"Notion request failed: {e}")
        return 1

    added, skipped_no_text, skipped_dupe = 0, 0, 0

    for row in rows:
        if row["review_status"] != "Posted" or not row["selected"]:
            continue

        if row["selected"] == "Retweet":
            # A quote-retweet's message is authored text in the user's voice;
            # a plain retweet (empty message) carries nothing to learn.
            text = row["retweet_message"].strip()
            post_type = "quote"
            if not text:
                continue
        else:
            text = NotionClient.selected_reply_text(row).strip()
            post_type = "reply"
            if not text:
                skipped_no_text += 1
                continue

        was_added = append_tweet(
            text,
            post_type=post_type,
            tweet_id=f"{NOTION_ID_PREFIX}{row['id']}",
            posted_url=row["url"],
        )
        added += was_added
        skipped_dupe += not was_added

    print(f"Added {added} sent repl(ies)/quote(s) to {CORPUS_PATH}.")
    if skipped_dupe:
        print(f"  {skipped_dupe} already in the corpus.")
    if skipped_no_text:
        print(
            f"  {skipped_no_text} marked Posted but had no reply text "
            "(the Selected field points at an empty reply)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
