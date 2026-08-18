"""One-time bootstrap: create the Notion database and seed the voice corpus.

Run once, before anything else. Everything it does is idempotent-guarded — it
refuses to re-create a database you already have.
"""

import argparse
import os
import re
import sys
from pathlib import Path

from gtm_agent.config import ConfigError, get_bearer_token, get_notion_token
from gtm_agent.harvest import resolve_user_id
from gtm_agent.notion_client import NotionApiError, NotionClient
from gtm_agent.store import Store
from gtm_agent.trajectory import run_main
from gtm_agent.voice_corpus import CORPUS_PATH, append_article, append_tweet
from gtm_agent.x_client import XApiError, XClient, full_text, is_long_post

ENV_PATH = Path(".env")
DB_ID_KEY = "NOTION_TWEET_DRAFTS_DB_ID"

TARGET_SHORT = 30
TARGET_LONG = 10
MAX_PAGES = 3  # bounds spend: each page is 100 reads at ~$0.005 each

# Matched against the raw string, not a dash-stripped one — page titles in Notion
# URLs ("My-Page-<id>") are themselves dash-separated, and stripping dashes first
# lets hex-ish characters from the title bleed into the match.
NOTION_ID_RE = re.compile(
    r"(?<![0-9a-fA-F])("
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"|[0-9a-fA-F]{32}"
    r")(?![0-9a-fA-F])"
)


def extract_page_id(url_or_id: str) -> str:
    """Pull the page id out of a Notion URL (or accept a bare/dashed id)."""
    candidates = NOTION_ID_RE.findall(url_or_id)
    if not candidates:
        raise ValueError(
            f"Couldn't find a Notion page id in {url_or_id!r}. Paste the full "
            "page URL, e.g. https://www.notion.so/Your-Page-<32 hex chars>"
        )
    # A URL may carry both a page id and a view id (?v=...); the page id is first.
    return candidates[0].replace("-", "")


def update_env_file(key: str, value: str, path: Path = ENV_PATH) -> bool:
    """Set key=value in .env. Returns True if the file was changed."""
    if not path.exists():
        return False
    lines = path.read_text().splitlines()
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            if line == f"{key}={value}":
                return False
            lines[i] = f"{key}={value}"
            path.write_text("\n".join(lines) + "\n")
            return True
    lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n")
    return True


def fetch_posts(client: XClient, user_id: str) -> tuple[list[dict], list[dict]]:
    """Return (short_posts, long_posts), newest first, capped at the targets."""
    short: list[dict] = []
    long_: list[dict] = []
    token = None

    for _ in range(MAX_PAGES):
        response = client.get_user_tweets(user_id, max_results=100, pagination_token=token)
        for tweet in response.get("data", []):
            long_form = is_long_post(tweet)
            bucket, cap = (long_, TARGET_LONG) if long_form else (short, TARGET_SHORT)
            if len(bucket) < cap:
                bucket.append(tweet)
        if len(short) >= TARGET_SHORT and len(long_) >= TARGET_LONG:
            break
        token = response.get("meta", {}).get("next_token")
        if not token:
            break

    return short, long_


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("notion_page", help="Notion page URL to create the database under")
    parser.add_argument("username", help="Your X username, without the @")
    parser.add_argument(
        "--force-new-db",
        action="store_true",
        help=f"Create a database even if {DB_ID_KEY} is already set",
    )
    args = parser.parse_args()

    try:
        get_notion_token()
        get_bearer_token()
    except ConfigError as e:
        print(f"Config error: {e}")
        return 1

    try:
        parent_page_id = extract_page_id(args.notion_page)
    except ValueError as e:
        print(e)
        return 1

    existing_db = os.environ.get(DB_ID_KEY, "").strip()
    if existing_db and not args.force_new_db:
        print(
            f"{DB_ID_KEY} is already set ({existing_db}).\n"
            "Setup is meant to run once. Re-run with --force-new-db to create "
            "another database anyway."
        )
        return 1

    notion = NotionClient()
    client = XClient()

    print(f"Creating 'Tweet Drafts' database under Notion page {parent_page_id}...")
    try:
        db_id = notion.create_database(parent_page_id)
    except NotionApiError as e:
        print(f"Failed to create the database: {e}")
        print(
            "\nIf this is a 404, the integration probably isn't shared with that "
            "page — open the page in Notion, then Share -> Invite -> your integration."
        )
        return 1
    print(f"  created database {db_id}")

    if update_env_file(DB_ID_KEY, db_id):
        print(f"  wrote {DB_ID_KEY} to {ENV_PATH}")

    print(f"\nFetching posts for @{args.username}...")
    store = Store()
    try:
        user_id = resolve_user_id(client, store, args.username)
        short, long_ = fetch_posts(client, user_id)
    except XApiError as e:
        print(f"X request failed: {e}")
        print(f"\nThe database was created ({db_id}) — re-run with --force-new-db "
              "only if you want a second one; otherwise seed the corpus later with "
              "gtm_agent/fetch_voice_corpus.py.")
        return 1

    added_short = sum(
        append_tweet(
            full_text(t),
            post_type="single-thread",
            tweet_id=t["id"],
            posted_url=f"https://x.com/{args.username}/status/{t['id']}",
        )
        for t in short
    )
    added_long = sum(
        append_article(
            full_text(t),
            title="",
            tweet_id=t["id"],
            posted_url=f"https://x.com/{args.username}/status/{t['id']}",
        )
        for t in long_
    )

    print(f"  {added_short} short post(s) -> tweets bucket")
    print(f"  {added_long} long post(s) -> articles bucket")
    print(f"  saved to {CORPUS_PATH}")

    if added_long == 0:
        print(
            "\nNote: no long-form posts found. X Articles can't be read through "
            "the API at all (the announcing tweet holds only a link), so the "
            "articles bucket can only be seeded from long posts. Article voice "
            "matching will be thin until you publish some through this pipeline."
        )

    print("\nSetup complete. Next: gtm_agent/x_oauth_login.py to authorize posting.")
    return 0


if __name__ == "__main__":
    sys.exit(run_main(main, __file__))
