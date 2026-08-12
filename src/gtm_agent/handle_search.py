"""Best-effort X handle discovery via search. X has no people-search
endpoint, so a bare name lookup is always a guess — this narrows it to two
tiers, both requiring the candidate account's display name to match the
author, and neither is trusted as final without a human glance:

  - high confidence: the account tweeted about this specific paper (matched
    by arXiv id or title words) — a real signal it's actually them.
  - low confidence: the account only showed up searching their bare name,
    kept solely because the name match was unique among results.

Recent search only covers the last 7 days, so this mostly helps for papers
being posted about now, not older ones.
"""

import re

from gtm_agent.x_client import XApiError, XClient

NAME_STRIP = re.compile(r"[^a-z ]")


def _normalize(name: str) -> str:
    return NAME_STRIP.sub("", name.lower()).strip()


def _name_matches(candidate: str, target: str) -> bool:
    return bool(candidate) and _normalize(candidate) == _normalize(target)


def find_x_handle(
    client: XClient, author_name: str, paper_title: str, arxiv_id: str | None = None
) -> dict | None:
    """Returns {"handle": "@user", "confidence": "high"|"low", "tweet_url": str|None}
    or None if nothing matched with enough confidence to surface."""
    identifier = arxiv_id or " ".join(paper_title.split()[:6])
    try:
        response = client.search_recent(f'"{author_name}" "{identifier}" -is:retweet', max_results=10)
    except XApiError:
        response = {}

    users = {u["id"]: u for u in (response.get("includes") or {}).get("users", [])}
    for tweet in response.get("data", []):
        user = users.get(tweet.get("author_id"))
        if user and _name_matches(user.get("name", ""), author_name):
            return {
                "handle": f"@{user['username']}",
                "confidence": "high",
                "tweet_url": f"https://x.com/{user['username']}/status/{tweet['id']}",
            }

    try:
        response = client.search_recent(f'"{author_name}" -is:retweet', max_results=20)
    except XApiError:
        return None

    users = {u["id"]: u for u in (response.get("includes") or {}).get("users", [])}
    matches = {u["username"]: u for u in users.values() if _name_matches(u.get("name", ""), author_name)}
    if len(matches) == 1:
        username = next(iter(matches))
        return {"handle": f"@{username}", "confidence": "low", "tweet_url": None}
    return None
