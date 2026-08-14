from gtm_agent.config import (
    ConfigError,
    get_response_calendar_db_id,
    get_tweet_drafts_db_id,
)
from gtm_agent.notion_client import NotionApiError, NotionClient
from gtm_agent.typefully_client import TypefullyApiError, get_draft
from gtm_agent.voice_corpus import append_tweet
from gtm_agent.x_client import tweet_id_from_url

STAGE = "Scheduled"


def _reconcile(
    notion: NotionClient,
    row: dict,
    text: str,
    post_type: str,
    mark_posted,
) -> tuple[bool, str]:
    """Check one row's pushed Typefully draft and, if it has resolved,
    update Notion + the voice corpus. Returns (changed, message) — changed
    is False (not a failure) while the draft is still pending."""
    draft_id = row["typefully_draft_id"]
    try:
        draft = get_draft(draft_id)
    except TypefullyApiError as e:
        return False, f"Row {row['id']}: failed to check Typefully draft {draft_id}: {e}"

    status = draft.get("status")

    if status == "published":
        posted_url = draft.get("x_published_url")
        tweet_id = tweet_id_from_url(posted_url) if posted_url else None
        try:
            mark_posted(row["id"])
        except NotionApiError as e:
            append_tweet(text, post_type=post_type, tweet_id=tweet_id, posted_url=posted_url)
            return True, f"Row {row['id']} published ({posted_url}) but failed to update Notion: {e}"
        append_tweet(text, post_type=post_type, tweet_id=tweet_id, posted_url=posted_url)
        return True, f"Row {row['id']} published: {posted_url}"

    if status == "error":
        message = f"Typefully draft {draft_id} failed to publish (status: error)."
        try:
            notion.set_post_error(row["id"], message)
        except NotionApiError as e:
            return True, f"Row {row['id']}: {message} (also failed to record Post Error in Notion: {e})"
        return True, f"Row {row['id']}: {message} Left for manual retry."

    return False, f"Row {row['id']}: still pending (Typefully status: {status})."


def main() -> int:
    try:
        notion = NotionClient()
        tweet_drafts_db_id = get_tweet_drafts_db_id()
        response_calendar_db_id = get_response_calendar_db_id()
    except ConfigError as e:
        print(f"Config error: {e}")
        return 1

    try:
        tweet_rows = [
            row
            for row in notion.get_rows_by_stage(tweet_drafts_db_id, STAGE)
            if row["typefully_draft_id"]
        ]
        response_rows = [
            row
            for row in notion.get_response_calendar_rows(response_calendar_db_id, status=STAGE)
            if row["typefully_draft_id"]
        ]
    except NotionApiError as e:
        print(f"Notion request failed: {e}")
        return 1

    if not tweet_rows and not response_rows:
        print("No pushed-to-Typefully rows to reconcile. Nothing to do.")
        return 0

    print(f"Checking {len(tweet_rows)} Tweet Drafts row(s) and {len(response_rows)} Response Calendar row(s)...")

    changed = 0

    for row in tweet_rows:
        ok, message = _reconcile(
            notion, row, row["final_text"], row["post_type"], notion.mark_posted
        )
        print(message)
        changed += ok

    for row in response_rows:
        text = NotionClient.selected_reply_text(row)
        ok, message = _reconcile(
            notion, row, text, "reply", notion.mark_response_row_posted
        )
        print(message)
        changed += ok

    print(f"Done. {changed} row(s) resolved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
