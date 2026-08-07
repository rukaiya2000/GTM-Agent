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


def parse_iso(dt_str: str) -> datetime:
    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def find_due_row(rows: list[dict], now: datetime) -> dict | None:
    due = [
        row
        for row in rows
        if row["scheduled_time"] and parse_iso(row["scheduled_time"]) < now
    ]
    if not due:
        return None
    due.sort(key=lambda r: parse_iso(r["scheduled_time"]))
    return due[0]


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

    if not rows:
        print(f"No rows in Stage = {STAGE}.")
        return 0

    now = datetime.now(timezone.utc)
    to_post = find_due_row(rows, now)
    if not to_post:
        print(f"No '{STAGE}' row has a Scheduled Time in the past — nothing due.")
        return 0

    try:
        access_token = get_valid_access_token(client_id, client_secret)
    except ConfigError as e:
        print(f"Config error: {e}")
        return 1

    ok, message = post_row(notion, to_post, access_token)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
