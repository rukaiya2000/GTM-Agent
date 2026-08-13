import time
from datetime import datetime, timezone

from gtm_agent.config import (
    ConfigError,
    get_tweet_drafts_db_id,
    get_x_client_id,
    get_x_client_secret,
)
from gtm_agent.notion_client import NotionApiError, NotionClient
from gtm_agent.posting import post_row
from gtm_agent.x_oauth import get_valid_access_token

STAGE = "Ready to post"
PAUSE_SECONDS_BETWEEN_POSTS = 5


def parse_iso(dt_str: str) -> datetime:
    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def due_rows_sorted(rows: list[dict], now: datetime) -> list[dict]:
    due = [
        row
        for row in rows
        if row["scheduled_time"] and parse_iso(row["scheduled_time"]) < now
    ]
    due.sort(key=lambda r: parse_iso(r["scheduled_time"]))
    return due


def main() -> int:
    try:
        notion = NotionClient()
        db_id = get_tweet_drafts_db_id()
        client_id = get_x_client_id()
        client_secret = get_x_client_secret()
    except ConfigError as e:
        print(f"Config error: {e}")
        return 1

    try:
        rows = notion.get_rows_by_stage(db_id, STAGE)
    except NotionApiError as e:
        print(f"Notion request failed: {e}")
        return 1

    now = datetime.now(timezone.utc)
    due = due_rows_sorted(rows, now)

    if not due:
        print(f"No '{STAGE}' row is due (Scheduled Time in the past). Nothing to do.")
        return 0

    print(f"{len(due)} row(s) due. Posting one at a time...")

    posted, failed = 0, 0
    for i, row in enumerate(due):
        try:
            access_token = get_valid_access_token(client_id, client_secret)
        except ConfigError as e:
            print(f"Config error: {e}")
            return 1

        ok, message = post_row(notion, row, access_token)
        print(message)
        posted += ok
        failed += not ok

        if i < len(due) - 1:
            time.sleep(PAUSE_SECONDS_BETWEEN_POSTS)

    print(f"Done. Posted {posted}, failed {failed}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
