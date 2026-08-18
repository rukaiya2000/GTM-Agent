"""Stage posts that mention you into the Response Calendar.

Replies to your posts, @-mentions and quotes are currently invisible to the rest
of the system. They land in the same Response Calendar as discovered posts, so
discover-and-draft-x-replies works on them unchanged.

Read-only against X. Nothing is replied to automatically.
"""

import argparse

from gtm_agent.config import ConfigError, get_response_calendar_db_id
from gtm_agent.discover import tweet_id_from_url
from gtm_agent.harvest import resolve_user_id
from gtm_agent.notion_client import NotionApiError, NotionClient
from gtm_agent.store import Store
from gtm_agent.x_client import XApiError, XClient, full_text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username", help="Your X username, without the @")
    parser.add_argument("--limit", type=int, default=20, help="Max mentions to fetch")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print without writing to Notion"
    )
    args = parser.parse_args()

    try:
        db_id = get_response_calendar_db_id()
        notion = NotionClient()
        client = XClient()
    except ConfigError as e:
        print(f"Config error: {e}")
        return 1

    store = Store()

    try:
        user_id = resolve_user_id(client, store, args.username)
        response = client.get_mentions(user_id, max_results=args.limit)
    except XApiError as e:
        print(f"X request failed: {e}")
        return 1

    mentions = response.get("data", [])
    if not mentions:
        print("No mentions found.")
        return 0

    authors = {
        u["id"]: u["username"] for u in response.get("includes", {}).get("users", [])
    }

    try:
        existing = notion.get_response_calendar_rows(db_id)
    except NotionApiError as e:
        print(f"Notion request failed: {e}")
        return 1

    already = {tweet_id_from_url(r["url"]) for r in existing}
    already.discard(None)

    fresh_ids = set(store.filter_unseen([m["id"] for m in mentions]))
    new = [m for m in mentions if m["id"] in fresh_ids and m["id"] not in already]
    store.mark_seen([m["id"] for m in mentions])

    if not new:
        print(f"{len(mentions)} mention(s) fetched, all already seen or staged.")
        return 0

    print(f"\n{len(new)} new mention(s):\n")
    for m in new:
        who = authors.get(m.get("author_id"), "i/web")
        print(f"  @{who}: {full_text(m)[:100]}")

    if args.dry_run:
        print("\n--dry-run: nothing written to Notion.")
        return 0

    written, failed = 0, 0
    for m in new:
        who = authors.get(m.get("author_id"), "i/web")
        url = f"https://x.com/{who}/status/{m['id']}"
        try:
            notion.create_discovery_row(
                db_id,
                full_text(m),
                url,
                tweet_date=m.get("created_at"),
            )
            written += 1
        except NotionApiError as e:
            print(f"Failed to stage {url}: {e}")
            failed += 1

    print(f"\nStaged {written} mention(s) as Status = New.")
    if failed:
        print(f"{failed} failed to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
