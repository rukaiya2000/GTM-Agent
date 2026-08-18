import sys

from gtm_agent.config import ConfigError
from gtm_agent.harvest import resolve_user_id
from gtm_agent.store import Store
from gtm_agent.trajectory import run_main
from gtm_agent.voice_corpus import append_tweet
from gtm_agent.x_client import XApiError, XClient

POST_COUNT = 30


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: fetch_voice_corpus.py <your_x_username>")
        return 1
    username = sys.argv[1]

    try:
        client = XClient()
    except ConfigError as e:
        print(f"Config error: {e}")
        return 1

    store = Store()

    try:
        user_id = resolve_user_id(client, store, username)
        response = client.get_user_tweets(user_id, max_results=POST_COUNT)
    except XApiError as e:
        print(f"X request failed: {e}")
        return 1

    # A plain timeline fetch can't tell whether a historical tweet was part of a
    # thread or standalone, so everything here is filed as single-thread. If you
    # know some of these were threads, that's a manual cleanup in voice_corpus.json.
    tweets = response.get("data", [])
    added, skipped = 0, 0
    for tweet in tweets:
        was_added = append_tweet(
            tweet["text"],
            post_type="single-thread",
            tweet_id=tweet["id"],
            posted_url=f"https://x.com/{username}/status/{tweet['id']}",
        )
        added += was_added
        skipped += not was_added

    print(f"Added {added} new post(s), skipped {skipped} already in voice_corpus.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_main(main, __file__))
