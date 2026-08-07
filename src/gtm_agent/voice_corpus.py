import json
from pathlib import Path

CORPUS_PATH = Path("voice_corpus.json")


def load_corpus(path: Path = CORPUS_PATH) -> dict:
    if not path.exists():
        return {"tweets": [], "articles": []}
    with open(path) as f:
        data = json.load(f)
    data.setdefault("tweets", [])
    data.setdefault("articles", [])
    return data


def save_corpus(corpus: dict, path: Path = CORPUS_PATH) -> None:
    with open(path, "w") as f:
        json.dump(corpus, f, indent=2)


def append_tweet(
    text: str,
    post_type: str = "single-thread",
    tweet_id: str | None = None,
    posted_url: str | None = None,
    path: Path = CORPUS_PATH,
) -> bool:
    """Append to the tweets bucket (single-thread or multi-thread posts).
    Returns False (no-op) if tweet_id is given and already present."""
    corpus = load_corpus(path)
    tweets = corpus["tweets"]

    if tweet_id and any(t.get("id") == tweet_id for t in tweets):
        return False

    tweets.append(
        {
            "id": tweet_id,
            "text": text,
            "posted_url": posted_url,
            "post_type": post_type,
        }
    )
    save_corpus(corpus, path)
    return True


def update_metrics(tweet_id: str, metrics: dict, path: Path = CORPUS_PATH) -> bool:
    """Attach performance metrics to a corpus entry, in whichever bucket it's in.
    Returns False if no entry has that id."""
    corpus = load_corpus(path)
    for bucket in ("tweets", "articles"):
        for entry in corpus[bucket]:
            if entry.get("id") == tweet_id:
                entry["metrics"] = metrics
                save_corpus(corpus, path)
                return True
    return False


def top_performing(limit: int = 15, path: Path = CORPUS_PATH) -> list[dict]:
    """Corpus tweets ordered by engagement rate, best first. Entries without
    metrics sort last rather than being dropped — a post with no data yet isn't
    evidence of a bad post."""
    tweets = load_corpus(path)["tweets"]
    scored = [t for t in tweets if (t.get("metrics") or {}).get("engagement_rate")]
    unscored = [t for t in tweets if t not in scored]
    scored.sort(key=lambda t: t["metrics"]["engagement_rate"], reverse=True)
    return (scored + unscored)[:limit]


def append_article(
    text: str,
    title: str = "",
    tweet_id: str | None = None,
    posted_url: str | None = None,
    path: Path = CORPUS_PATH,
) -> bool:
    """Append to the articles bucket (long-form posts).
    Returns False (no-op) if tweet_id is given and already present."""
    corpus = load_corpus(path)
    articles = corpus["articles"]

    if tweet_id and any(a.get("id") == tweet_id for a in articles):
        return False

    articles.append(
        {
            "id": tweet_id,
            "title": title,
            "text": text,
            "posted_url": posted_url,
        }
    )
    save_corpus(corpus, path)
    return True
