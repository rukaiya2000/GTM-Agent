import math
from datetime import datetime, timezone

DEFAULT_WEIGHTS = {
    "like_count": 1.0,
    "retweet_count": 2.0,
    "reply_count": 1.5,
    "quote_count": 2.0,
    "bookmark_count": 1.5,
    # Impressions run orders of magnitude larger than likes, so this weight is
    # small on purpose — it nudges ranking without swamping real engagement.
    # public_metrics.impression_count is also frequently 0 for other people's
    # posts, so nothing here may depend on it being present.
    "impression_count": 0.01,
}


def engagement_score(
    public_metrics: dict,
    created_at: str | None = None,
    *,
    weights: dict | None = None,
    half_life_hours: float | None = None,
    now: datetime | None = None,
) -> float:
    weights = weights or DEFAULT_WEIGHTS
    score = sum(
        weights.get(field, 0.0) * public_metrics.get(field, 0)
        for field in weights
    )

    if half_life_hours and created_at:
        now = now or datetime.now(timezone.utc)
        posted_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        age_hours = (now - posted_at).total_seconds() / 3600
        decay = math.pow(0.5, age_hours / half_life_hours)
        score *= decay

    return score


def rank_tweets(
    tweets: list[dict],
    *,
    weights: dict | None = None,
    half_life_hours: float | None = None,
) -> list[dict]:
    scored = [
        {
            **tweet,
            "score": engagement_score(
                tweet.get("public_metrics", {}),
                tweet.get("created_at"),
                weights=weights,
                half_life_hours=half_life_hours,
            ),
        }
        for tweet in tweets
    ]
    return sorted(scored, key=lambda t: t["score"], reverse=True)
