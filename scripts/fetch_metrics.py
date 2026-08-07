"""Pull performance data for your own posts into the voice corpus.

Turns voice_corpus.json from a flat style reference into a feedback loop:
polish-tweet can then prefer exemplars that actually landed instead of treating
every past post as equally good.

Private metrics (impressions, profile clicks) exist only for your own tweets from
the last 30 days, so run this regularly if you want history to accumulate.
"""

from gtm_agent.config import (
    ConfigError,
    get_x_client_id,
    get_x_client_secret,
)
from gtm_agent.voice_corpus import CORPUS_PATH, load_corpus, update_metrics
from gtm_agent.x_client import XApiError, extract_metrics, get_tweets_with_metrics
from gtm_agent.x_oauth import get_valid_access_token


def main() -> int:
    try:
        client_id = get_x_client_id()
        client_secret = get_x_client_secret()
        access_token = get_valid_access_token(client_id, client_secret)
    except ConfigError as e:
        print(f"Config error: {e}")
        return 1

    corpus = load_corpus()
    ids = [
        entry["id"]
        for bucket in ("tweets", "articles")
        for entry in corpus[bucket]
        if entry.get("id")
    ]

    if not ids:
        print(f"No entries with tweet ids in {CORPUS_PATH} — nothing to look up.")
        return 0

    print(f"Looking up metrics for {len(ids)} post(s)...")
    try:
        tweets = get_tweets_with_metrics(ids, access_token)
    except XApiError as e:
        print(f"X request failed: {e}")
        return 1

    updated, with_private = 0, 0
    for tweet in tweets:
        metrics = extract_metrics(tweet)
        if update_metrics(tweet["id"], metrics):
            updated += 1
        if tweet.get("non_public_metrics"):
            with_private += 1

    missing = len(ids) - len(tweets)
    print(f"Updated {updated} entr(ies) in {CORPUS_PATH}.")
    print(f"  {with_private} had private metrics (impressions, profile clicks).")
    if with_private < len(tweets):
        print(
            f"  {len(tweets) - with_private} had public metrics only — normal for "
            "posts older than 30 days."
        )
    if missing:
        print(f"  {missing} id(s) returned nothing (deleted, or not yours).")

    ranked = [
        (e["metrics"]["engagement_rate"], e["text"][:60])
        for e in load_corpus()["tweets"]
        if (e.get("metrics") or {}).get("engagement_rate")
    ]
    if ranked:
        ranked.sort(reverse=True)
        print("\nTop performers by engagement rate:")
        for rate, text in ranked[:5]:
            print(f"  {rate:7.2%}  {text}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
