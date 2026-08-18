import sys

from gtm_agent.config import ConfigError, get_tweet_drafts_db_id
from gtm_agent.harvest import resolve_user_id
from gtm_agent.notion_client import NotionApiError, NotionClient
from gtm_agent.store import Store
from gtm_agent.trajectory import run_main
from gtm_agent.x_client import XApiError, XClient

MAX_PAGES = 3  # up to 300 tweets per run, bounds cost per PRD's per-read pricing


def fetch_all_tweets(client: XClient, user_id: str) -> list[dict]:
    tweets: list[dict] = []
    pagination_token = None
    for _ in range(MAX_PAGES):
        response = client.get_user_tweets(
            user_id, max_results=100, pagination_token=pagination_token
        )
        tweets.extend(response.get("data", []))
        pagination_token = response.get("meta", {}).get("next_token")
        if not pagination_token:
            break
    return tweets, pagination_token is not None


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: sync_posted.py <your_x_username>")
        return 1
    username = sys.argv[1]

    try:
        db_id = get_tweet_drafts_db_id()
        notion = NotionClient()
        client = XClient()
    except ConfigError as e:
        print(f"Config error: {e}")
        return 1

    store = Store()

    try:
        user_id = resolve_user_id(client, store, username)
        tweets, more_available = fetch_all_tweets(client, user_id)
    except XApiError as e:
        print(f"X request failed: {e}")
        return 1

    try:
        existing_rows = notion.get_all_rows(db_id)
    except NotionApiError as e:
        print(f"Notion request failed: {e}")
        return 1

    # No Posted URL / tweet-ID property exists in Notion anymore, so this can only
    # dedupe by exact Final Text match — weaker than ID matching (an edited or
    # truncated import could re-add), but avoids blindly re-importing everything.
    existing_texts = {row["final_text"] for row in existing_rows if row["final_text"]}

    imported, skipped = 0, 0
    for tweet in tweets:
        if tweet["text"] in existing_texts:
            skipped += 1
            continue
        try:
            notion.create_posted_row(
                db_id,
                title=tweet["text"][:60],
                final_text=tweet["text"],
            )
        except NotionApiError as e:
            print(f"Failed to import tweet {tweet['id']}: {e}")
            continue
        existing_texts.add(tweet["text"])
        imported += 1

    print(f"Imported {imported} new post(s), skipped {skipped} already-logged.")
    if more_available:
        print(
            f"More history exists beyond the last {MAX_PAGES * 100} tweets fetched — "
            "re-run to fetch further back if needed."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(run_main(main, __file__))
