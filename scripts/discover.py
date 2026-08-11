"""Find posts worth engaging with and stage them in the Response Calendar.

Sources come from interests.md (accounts + topics). Ranking is plain engagement
math — no LLM — so re-running is cheap and deterministic. The draft-x-replies
skill does the relevance judgment afterwards, using the `status` column
(Commented / Rejected / not-commented) on existing rows as signal.
"""

import argparse
import re

from gtm_agent.config import ConfigError, get_response_calendar_db_id
from gtm_agent.harvest import resolve_user_id
from gtm_agent.interests import load_interests
from gtm_agent.notion_client import NotionApiError, NotionClient
from gtm_agent.ranking import rank_tweets
from gtm_agent.store import Store
from gtm_agent.x_client import XApiError, XClient, full_text

DEFAULT_LIMIT = 10
PER_ACCOUNT = 20
PER_TOPIC = 20
TWEET_ID_RE = re.compile(r"/status/(\d+)")


def tweet_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    match = TWEET_ID_RE.search(url)
    return match.group(1) if match else None


def collect_from_accounts(
    client: XClient, store: Store, accounts: list[str]
) -> tuple[list[dict], list[str]]:
    tweets, problems = [], []
    for username in accounts:
        try:
            user_id = resolve_user_id(client, store, username)
            response = client.get_user_tweets(user_id, max_results=PER_ACCOUNT)
        except XApiError as e:
            problems.append(f"@{username}: {e}")
            continue
        for tweet in response.get("data", []):
            tweet["username"] = username
            tweets.append(tweet)
    return tweets, problems


def collect_from_topics(
    client: XClient, topics: list[str]
) -> tuple[list[dict], list[str]]:
    tweets, problems = [], []
    for topic in topics:
        try:
            response = client.search_recent(topic, max_results=PER_TOPIC)
        except XApiError as e:
            problems.append(f"topic {topic!r}: {e}")
            continue
        users = {
            u["id"]: u["username"]
            for u in response.get("includes", {}).get("users", [])
        }
        for tweet in response.get("data", []):
            tweet["username"] = users.get(tweet.get("author_id"), "i/web")
            tweet["matched_topic"] = topic
            tweets.append(tweet)
    return tweets, problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT,
        help=f"How many top-ranked posts to stage (default {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Rank and print, but write nothing to Notion",
    )
    args = parser.parse_args()

    try:
        interests = load_interests()
    except FileNotFoundError as e:
        print(e)
        return 1

    if not interests["accounts"] and not interests["topics"]:
        print("interests.md has no accounts or topics — add some and re-run.")
        return 1

    try:
        db_id = get_response_calendar_db_id()
        notion = NotionClient()
        client = XClient()
    except ConfigError as e:
        print(f"Config error: {e}")
        return 1

    store = Store()
    problems: list[str] = []

    tweets, account_problems = collect_from_accounts(
        client, store, interests["accounts"]
    )
    problems += account_problems

    if interests["topics"]:
        topic_tweets, topic_problems = collect_from_topics(client, interests["topics"])
        tweets += topic_tweets
        problems += topic_problems

    if problems:
        print("Some sources failed:")
        for p in problems:
            print(f"  - {p}")
        if any("search/recent" in p or "403" in p or "401" in p for p in problems):
            print(
                "  (a topic failure here usually means recent-search isn't callable "
                "on your plan — see x-req.md open item 2)"
            )

    if not tweets:
        print("Nothing fetched.")
        return 1

    try:
        existing = notion.get_response_calendar_rows(db_id)
    except NotionApiError as e:
        print(f"Notion request failed: {e}")
        return 1

    already = {tweet_id_from_url(r["url"]) for r in existing}
    already.discard(None)

    fresh_ids = set(store.filter_unseen([t["id"] for t in tweets]))
    candidates = [
        t for t in tweets if t["id"] in fresh_ids and t["id"] not in already
    ]
    store.mark_seen([t["id"] for t in tweets])

    if not candidates:
        print(f"Fetched {len(tweets)} post(s), all previously seen or already staged.")
        return 0

    ranked = rank_tweets(candidates)[: args.limit]

    print(f"\n{len(ranked)} post(s) to stage (from {len(candidates)} new):\n")
    for t in ranked:
        url = f"https://x.com/{t['username']}/status/{t['id']}"
        print(f"  [{t['score']:7.1f}] {url}")
        print(f"             {full_text(t)[:110]}")

    if args.dry_run:
        print("\n--dry-run: nothing written to Notion.")
        return 0

    written, failed = 0, 0
    for t in ranked:
        url = f"https://x.com/{t['username']}/status/{t['id']}"
        try:
            notion.create_discovery_row(
                db_id, full_text(t), url, tweet_date=t.get("created_at")
            )
            written += 1
        except NotionApiError as e:
            print(f"Failed to stage {url}: {e}")
            failed += 1

    print(f"\nStaged {written} post(s) to Response Calendar as Status = New.")
    if failed:
        print(f"{failed} failed to write.")
    print("Next: run the draft-x-replies skill to prune by past signal.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
