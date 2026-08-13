
from gtm_agent.ranking import rank_tweets
from gtm_agent.store import Store
from gtm_agent.x_client import XApiError, XClient


def resolve_user_id(client: XClient, store: Store, username: str) -> str:
    cached = store.get_cached_user_id(username)
    if cached:
        return cached
    user = client.get_user_by_username(username)
    if "data" not in user:
        # Suspended/nonexistent accounts come back as an errors payload with
        # HTTP 200 — surface as XApiError so callers degrade per source.
        detail = (user.get("errors") or [{}])[0].get("detail", "user not found")
        raise XApiError(200, detail)
    user_id = user["data"]["id"]
    store.cache_user_id(username, user_id)
    return user_id


def fetch_account_tweets(
    client: XClient, store: Store, username: str, max_results: int = 20
) -> list[dict]:
    user_id = resolve_user_id(client, store, username)
    response = client.get_user_tweets(user_id, max_results=max_results)
    tweets = response.get("data", [])
    for tweet in tweets:
        tweet["username"] = username
    return tweets


def run_harvest(
    client: XClient,
    store: Store,
    accounts: list[str],
    topics: list[str] | None = None,
    max_results_per_account: int = 20,
) -> list[dict]:
    if topics:
        raise NotImplementedError(
            "Topic search (recent-search) is deferred until availability is "
            "confirmed on the pay-per-use account — see x-req.md open item 2."
        )

    all_new_tweets: list[dict] = []
    for username in accounts:
        tweets = fetch_account_tweets(
            client, store, username, max_results=max_results_per_account
        )
        tweet_ids = [t["id"] for t in tweets]
        unseen_ids = set(store.filter_unseen(tweet_ids))
        new_tweets = [t for t in tweets if t["id"] in unseen_ids]
        all_new_tweets.extend(new_tweets)
        store.mark_seen(tweet_ids)

    return rank_tweets(all_new_tweets)
