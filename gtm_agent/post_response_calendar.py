import time
from datetime import datetime, timezone

from gtm_agent.config import (
    ConfigError,
    get_response_calendar_db_id,
    get_x_client_id,
    get_x_client_secret,
)
from gtm_agent.notion_client import NotionApiError, NotionClient
from gtm_agent.posting import (
    REPLY_FIELDS,
    post_response_calendar_row,
    push_response_row_to_typefully,
)
from gtm_agent.trajectory import run_main
from gtm_agent.x_oauth import get_valid_access_token

STATUS = "Ready to post"
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
        db_id = get_response_calendar_db_id()
        client_id = get_x_client_id()
        client_secret = get_x_client_secret()
    except ConfigError as e:
        print(f"Config error: {e}")
        return 1

    try:
        rows = notion.get_response_calendar_rows(db_id, status=STATUS)
    except NotionApiError as e:
        print(f"Notion request failed: {e}")
        return 1

    # Reply rows push to Typefully as soon as they're Ready to post — Typefully
    # owns the scheduling gate from there, not a local due-time check. Only
    # rows not yet pushed (no Typefully Draft ID) are eligible. Retweet rows
    # keep the local due-time gate and post immediately via the direct X API.
    to_push = [
        row
        for row in rows
        if row.get("selected") in REPLY_FIELDS and not row["typefully_draft_id"]
    ]
    now = datetime.now(timezone.utc)
    due = due_rows_sorted(
        [row for row in rows if row.get("selected") not in REPLY_FIELDS], now
    )

    if not to_push and not due:
        print(f"No '{STATUS}' row to push or due. Nothing to do.")
        return 0

    pushed, posted, failed = 0, 0, 0

    if to_push:
        print(f"{len(to_push)} row(s) to push to Typefully...")
        for row in to_push:
            ok, message = push_response_row_to_typefully(notion, row)
            print(message)
            pushed += ok
            failed += not ok

    if due:
        print(f"{len(due)} row(s) due for direct posting...")
        for i, row in enumerate(due):
            try:
                access_token = get_valid_access_token(client_id, client_secret)
            except ConfigError as e:
                print(f"Config error: {e}")
                return 1

            ok, message = post_response_calendar_row(notion, row, access_token)
            print(message)
            posted += ok
            failed += not ok

            if i < len(due) - 1:
                time.sleep(PAUSE_SECONDS_BETWEEN_POSTS)

    print(f"Done. Pushed {pushed} to Typefully, posted {posted} directly, failed {failed}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_main(main, __file__))
