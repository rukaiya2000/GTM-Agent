"""Find accounts worth tracking, and promote approved ones into interests.md.

Two modes:

  discover_accounts.py            search your topics, stage authors for review
  discover_accounts.py --promote  copy Approved accounts into interests.md

The review step is deliberately manual — you decide who's worth following, in the
Discovery Database, and only then do they start costing read budget in discover.py.
"""

import argparse
import re
from pathlib import Path

from gtm_agent.config import ConfigError, get_discovery_db_id
from gtm_agent.interests import DEFAULT_INTERESTS_PATH, load_interests
from gtm_agent.notion_client import NotionApiError, NotionClient
from gtm_agent.x_client import XApiError, XClient, full_text

PER_TOPIC = 20
MIN_FOLLOWERS = 500  # filters out brand-new and throwaway accounts


def add_accounts_to_interests(
    usernames: list[str], path: Path = DEFAULT_INTERESTS_PATH
) -> list[str]:
    """Append usernames under the Accounts heading. Returns the ones added."""
    text = path.read_text()
    existing = {a.lower() for a in load_interests(path)["accounts"]}
    new = [u for u in usernames if u.lower() not in existing]
    if not new:
        return []

    lines = text.splitlines()
    # Insert after the last bullet in the Accounts section, so the file's prose
    # and section order survive.
    heading, insert_at = None, None
    for i, line in enumerate(lines):
        m = re.match(r"^\s*#{1,6}\s*(.+?)\s*$", line)
        if m:
            heading = m.group(1).strip().lower()
            continue
        if heading == "accounts" and re.match(r"^\s*[-*]\s+", line):
            insert_at = i + 1

    if insert_at is None:  # no bullets yet — put them right after the heading
        for i, line in enumerate(lines):
            m = re.match(r"^\s*#{1,6}\s*(.+?)\s*$", line)
            if m and m.group(1).strip().lower() == "accounts":
                insert_at = i + 1
                break
    if insert_at is None:
        raise ValueError(f"No '## Accounts' heading found in {path}")

    for offset, username in enumerate(new):
        lines.insert(insert_at + offset, f"- @{username}")
    path.write_text("\n".join(lines) + "\n")
    return new


def promote(notion: NotionClient, db_id: str) -> int:
    try:
        rows = notion.get_discovery_rows(db_id)
    except NotionApiError as e:
        print(f"Notion request failed: {e}")
        return 1

    approved = [r["username"] for r in rows if r["review_status"] == "Approved"]
    approved = [u for u in approved if u]
    if not approved:
        print("No accounts marked Approved in the Discovery Database.")
        return 0

    added = add_accounts_to_interests(approved)
    if added:
        print(f"Added {len(added)} account(s) to {DEFAULT_INTERESTS_PATH}:")
        for u in added:
            print(f"  @{u}")
    else:
        print(f"All {len(approved)} approved account(s) already in interests.md.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--promote", action="store_true",
        help="Copy Approved accounts into interests.md instead of searching",
    )
    parser.add_argument(
        "--min-followers", type=int, default=MIN_FOLLOWERS,
        help=f"Skip accounts below this follower count (default {MIN_FOLLOWERS})",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print, don't write")
    args = parser.parse_args()

    try:
        db_id = get_discovery_db_id()
        notion = NotionClient()
    except ConfigError as e:
        print(f"Config error: {e}")
        return 1

    if args.promote:
        return promote(notion, db_id)

    try:
        client = XClient()
        interests = load_interests()
    except (ConfigError, FileNotFoundError) as e:
        print(f"{e}")
        return 1

    if not interests["topics"]:
        print("interests.md has no topics — account discovery searches by topic.")
        return 1

    try:
        existing = {r["username"].lower() for r in notion.get_discovery_rows(db_id)}
    except NotionApiError as e:
        print(f"Notion request failed: {e}")
        return 1
    existing |= {a.lower() for a in interests["accounts"]}

    found: dict[str, dict] = {}
    problems = []
    for topic in interests["topics"]:
        try:
            response = client.search_recent(topic, max_results=PER_TOPIC)
        except XApiError as e:
            problems.append(f"topic {topic!r}: {e}")
            continue

        users = {u["id"]: u for u in response.get("includes", {}).get("users", [])}
        for tweet in response.get("data", []):
            user = users.get(tweet.get("author_id"))
            if not user:
                continue
            username = user["username"]
            if username.lower() in existing or username.lower() in found:
                continue
            followers = (user.get("public_metrics") or {}).get("followers_count")
            if followers is not None and followers < args.min_followers:
                continue
            found[username.lower()] = {
                "username": username,
                "name": user.get("name", ""),
                "bio": user.get("description", ""),
                "followers": followers,
                "topic": topic,
                "sample": full_text(tweet),
                "sample_url": f"https://x.com/{username}/status/{tweet['id']}",
            }

    if problems:
        print("Some topics failed:")
        for p in problems:
            print(f"  - {p}")
        print(
            "  (this usually means recent-search isn't callable on your plan — "
            "see x-req.md open item 2)"
        )

    if not found:
        print("No new accounts found.")
        return 0

    print(f"\n{len(found)} new account(s):\n")
    for a in found.values():
        followers = f"{a['followers']:,}" if a["followers"] is not None else "?"
        print(f"  @{a['username']} ({followers} followers) — via {a['topic']!r}")
        print(f"      {a['bio'][:90]}")

    if args.dry_run:
        print("\n--dry-run: nothing written to Notion.")
        return 0

    written = 0
    for a in found.values():
        try:
            notion.create_discovery_account_row(
                db_id,
                name=a["name"],
                username=a["username"],
                bio=a["bio"],
                follower_count=a["followers"],
                matched_query=a["topic"],
                sample_tweet=a["sample"],
                sample_tweet_url=a["sample_url"],
            )
            written += 1
        except NotionApiError as e:
            print(f"Failed to stage @{a['username']}: {e}")

    print(f"\nStaged {written} account(s) with Review Status = New.")
    print("Mark the good ones Approved, then run with --promote.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
