from gtm_agent.config import ConfigError
from gtm_agent.harvest import run_harvest
from gtm_agent.interests import load_interests
from gtm_agent.store import Store
from gtm_agent.trajectory import run_main
from gtm_agent.x_client import XApiError, XClient


def main() -> int:
    try:
        interests = load_interests()
    except FileNotFoundError as e:
        print(e)
        return 1

    if not interests["accounts"] and not interests["topics"]:
        print("interests.md has no accounts or topics — add some and re-run.")
        return 1

    try:
        client = XClient()
    except ConfigError as e:
        print(f"Config error: {e}")
        return 1

    store = Store()

    try:
        ranked = run_harvest(
            client, store, interests["accounts"], interests["topics"]
        )
    except XApiError as e:
        print(f"Request failed: {e}")
        return 1

    if not ranked:
        print("No new posts since last run.")
        return 0

    for tweet in ranked:
        link = f"https://x.com/{tweet['username']}/status/{tweet['id']}"
        print(f"[{tweet['score']:.1f}] {link}")
        print(f"  {tweet['text'][:200]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(run_main(main, __file__))
