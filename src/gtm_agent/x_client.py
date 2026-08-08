import time

import requests

from gtm_agent.config import get_bearer_token

BASE_URL = "https://api.x.com/2"
THREAD_TWEET_PAUSE_SECONDS = 2


class XApiError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(f"X API error {status_code}: {message}")
        self.status_code = status_code


class XClient:
    def __init__(self, bearer_token: str | None = None):
        self._bearer_token = bearer_token or get_bearer_token()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._bearer_token}"}

    def _get(self, path: str, params: dict | None = None) -> dict:
        response = requests.get(
            f"{BASE_URL}{path}", headers=self._headers(), params=params
        )
        if response.status_code == 401:
            raise XApiError(401, "unauthorized — check X_BEARER_TOKEN")
        if response.status_code == 402:
            raise XApiError(402, "payment required — pay-per-use credits depleted")
        if not response.ok:
            raise XApiError(response.status_code, response.text)
        return response.json()

    def get_user_by_username(self, username: str) -> dict:
        return self._get(f"/users/by/username/{username}")

    def get_mentions(
        self, user_id: str, max_results: int = 20, pagination_token: str | None = None
    ) -> dict:
        """Posts mentioning this user — replies to their posts, @-mentions, quotes."""
        params = {
            "max_results": max_results,
            "tweet.fields": "public_metrics,created_at,note_tweet",
            "expansions": "author_id",
            "user.fields": "username",
        }
        if pagination_token:
            params["pagination_token"] = pagination_token
        return self._get(f"/users/{user_id}/mentions", params=params)

    def search_recent(self, query: str, max_results: int = 20) -> dict:
        """Search posts from the last 7 days. Availability on pay-per-use is
        unconfirmed — see x-req.md open item 2. Full-archive search is Enterprise."""
        return self._get(
            "/tweets/search/recent",
            params={
                "query": query,
                "max_results": max_results,
                "tweet.fields": "public_metrics,created_at,note_tweet",
                "expansions": "author_id",
                # name/description/public_metrics are what account discovery
                # needs to show who an author is and filter by follower count.
                "user.fields": "username,name,description,public_metrics",
            },
        )

    def get_user_tweets(
        self,
        user_id: str,
        max_results: int = 20,
        pagination_token: str | None = None,
    ) -> dict:
        params = {
            "max_results": max_results,
            # note_tweet carries the full text of long posts (>280 chars, Premium).
            # Without it, `text` is truncated for those.
            "tweet.fields": "public_metrics,created_at,note_tweet",
            "exclude": "retweets,replies",
        }
        if pagination_token:
            params["pagination_token"] = pagination_token
        return self._get(f"/users/{user_id}/tweets", params=params)


def get_tweets_with_metrics(tweet_ids: list[str], access_token: str) -> list[dict]:
    """Look up your own tweets with private analytics attached.

    non_public_metrics / organic_metrics require user-context OAuth and only
    exist for **your own** tweets from the **last 30 days** — older ones come
    back with public metrics only, which is why this asks for both."""
    results: list[dict] = []
    for start in range(0, len(tweet_ids), 100):  # the endpoint caps ids at 100
        batch = tweet_ids[start : start + 100]
        response = requests.get(
            f"{BASE_URL}/tweets",
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "ids": ",".join(batch),
                "tweet.fields": "public_metrics,non_public_metrics,organic_metrics,created_at",
            },
        )
        if response.status_code == 401:
            raise XApiError(401, "unauthorized — X OAuth token missing/expired/invalid")
        if not response.ok:
            raise XApiError(response.status_code, response.text)
        results.extend(response.json().get("data", []))
    return results


def extract_metrics(tweet: dict) -> dict:
    """Flatten the three metric blocks into one dict, preferring private sources
    for impressions since public_metrics.impression_count is often 0."""
    public = tweet.get("public_metrics") or {}
    non_public = tweet.get("non_public_metrics") or {}
    organic = tweet.get("organic_metrics") or {}

    impressions = (
        non_public.get("impression_count")
        or organic.get("impression_count")
        or public.get("impression_count")
        or 0
    )
    engagements = (
        public.get("like_count", 0)
        + public.get("retweet_count", 0)
        + public.get("reply_count", 0)
        + public.get("quote_count", 0)
    )
    return {
        "impressions": impressions,
        "likes": public.get("like_count", 0),
        "retweets": public.get("retweet_count", 0),
        "replies": public.get("reply_count", 0),
        "quotes": public.get("quote_count", 0),
        "profile_clicks": non_public.get("user_profile_clicks", 0),
        "engagements": engagements,
        # Rate matters more than raw counts — it separates "this resonated" from
        # "this happened to be seen by a lot of people".
        "engagement_rate": round(engagements / impressions, 5) if impressions else None,
    }


def full_text(tweet: dict) -> str:
    """The full text of a tweet. Long posts (Premium, >280 chars) put their real
    text in note_tweet and leave `text` truncated, so prefer note_tweet."""
    note = tweet.get("note_tweet") or {}
    return note.get("text") or tweet.get("text", "")


def is_long_post(tweet: dict) -> bool:
    """True for long-form posts. Note: X Articles are NOT retrievable via the
    API at all — the announcing tweet holds only a t.co link — so this is the
    closest available source of long-form voice."""
    return bool((tweet.get("note_tweet") or {}).get("text"))


def _post(path: str, access_token: str, body: dict | None = None) -> dict:
    """POST to the X API with a user-context OAuth 2.0 access token. The app-only
    bearer token used for reads will not work here. See scripts/x_oauth_login.py."""
    response = requests.post(
        f"{BASE_URL}{path}",
        headers={"Authorization": f"Bearer {access_token}"},
        json=body if body is not None else {},
    )
    if response.status_code == 401:
        raise XApiError(401, "unauthorized — X OAuth token missing/expired/invalid")
    if response.status_code == 402:
        raise XApiError(402, "payment required — pay-per-use credits depleted")
    if response.status_code == 403:
        raise XApiError(
            403,
            f"forbidden — the account may lack the required entitlement "
            f"(Articles need X Premium): {response.text}",
        )
    if not response.ok:
        raise XApiError(response.status_code, response.text)
    return response.json()


def post_tweet(
    text: str, access_token: str, reply_to_tweet_id: str | None = None
) -> dict:
    """Post a tweet.

    Pass reply_to_tweet_id to chain this tweet as a reply to a previous one —
    that's how threads are built, one call per tweet."""
    body = {"text": text}
    if reply_to_tweet_id:
        body["reply"] = {"in_reply_to_tweet_id": reply_to_tweet_id}
    return _post("/tweets", access_token, body)


def send_dm(username: str, text: str, access_token: str, bearer_token: str | None = None) -> dict:
    """Send a direct message to an X user by @handle.

    The DM endpoint needs a numeric user id, not a handle, so this resolves
    it first via a read call (app-only bearer token), then sends via the
    user-context OAuth token — requires the dm.write scope, added to
    x_oauth.SCOPES; re-run x_oauth_login.py if your saved token predates
    that."""
    lookup = XClient(bearer_token)
    user = lookup.get_user_by_username(username.lstrip("@"))
    participant_id = user["data"]["id"]
    return _post(f"/dm_conversations/with/{participant_id}/messages", access_token, {"text": text})


class ThreadPostError(RuntimeError):
    """Raised when a thread fails partway through. posted_tweet_ids holds the
    IDs of tweets that DID succeed before the failure — those are live on X and
    were not rolled back."""

    def __init__(self, message: str, posted_tweet_ids: list[str]):
        super().__init__(message)
        self.posted_tweet_ids = posted_tweet_ids


def post_thread(tweets: list[str], access_token: str) -> list[dict]:
    """Post a sequence of tweets chained as replies (a thread). Stops and raises
    ThreadPostError on the first failure — does not retry or roll back tweets
    already posted."""
    results: list[dict] = []
    reply_to: str | None = None

    for i, text in enumerate(tweets):
        try:
            result = post_tweet(text, access_token, reply_to_tweet_id=reply_to)
        except XApiError as e:
            posted_ids = [r["data"]["id"] for r in results]
            raise ThreadPostError(
                f"Thread failed at tweet {i + 1}/{len(tweets)}: {e}. "
                f"{len(results)} tweet(s) before it already posted and were not "
                "rolled back.",
                posted_tweet_ids=posted_ids,
            ) from e

        results.append(result)
        reply_to = result["data"]["id"]

        if i < len(tweets) - 1:
            time.sleep(THREAD_TWEET_PAUSE_SECONDS)

    return results


def text_to_content_state(body: str) -> dict:
    """Convert plain text into the DraftJS content_state the Articles API wants.
    Each line becomes one block (a paragraph); blank lines are preserved as empty
    blocks so paragraph spacing survives. Rich formatting, embeds, and images are
    supported by the API via `entities` but not produced here — plain text only."""
    lines = body.split("\n")
    return {
        "blocks": [{"text": line, "type": "unstyled"} for line in lines],
        "entities": [],
    }


class ArticlePublishError(RuntimeError):
    """Raised when an Article draft was created but publishing it failed. The
    draft exists on X and was not cleaned up — draft_id identifies it so it can
    be published or deleted by hand."""

    def __init__(self, message: str, draft_id: str):
        super().__init__(message)
        self.draft_id = draft_id


def create_article_draft(title: str, body: str, access_token: str) -> dict:
    return _post(
        "/articles/draft",
        access_token,
        {"title": title, "content_state": text_to_content_state(body)},
    )


def publish_article(article_id: str, access_token: str) -> dict:
    return _post(f"/articles/{article_id}/publish", access_token)


def post_article(title: str, body: str, access_token: str) -> dict:
    """Create and publish a long-form Article. Two API calls — if the second
    fails, the draft is left on X and ArticlePublishError carries its id."""
    draft = create_article_draft(title, body, access_token)
    draft_id = draft["data"]["id"]

    try:
        return publish_article(draft_id, access_token)
    except XApiError as e:
        raise ArticlePublishError(
            f"Article draft {draft_id} was created but publishing failed: {e}. "
            "The draft still exists on X — publish or delete it manually.",
            draft_id=draft_id,
        ) from e

    return results
