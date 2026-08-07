"""Feed replies you actually sent into the voice corpus.

A reply you chose and posted is as much your voice as an original post, but it
only lives in Notion. This copies it into voice_corpus.json so draft-replies and
polish-tweet can learn from it.

Reads rows where `Posted` is checked and `Selected` names a reply with text.
`Selected = Like/RT` is skipped — there's no text to learn from.
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
        if not row["posted"] or not row["selected"]:
            continue

        text = NotionClient.selected_reply_text(row).strip()
        if not text:
            skipped_no_text += 1
            continue

        was_added = append_tweet(
            text,
            post_type="reply",
            tweet_id=f"{NOTION_ID_PREFIX}{row['id']}",
            posted_url=row["url"],
        )
        added += was_added
        skipped_dupe += not was_added

    print(f"Added {added} sent repl(ies) to {CORPUS_PATH} as post_type=reply.")
    if skipped_dupe:
        print(f"  {skipped_dupe} already in the corpus.")
    if skipped_no_text:
        print(
            f"  {skipped_no_text} marked Posted but had no reply text "
            "(Like/RT, or the Selected field points at an empty reply)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
