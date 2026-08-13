import re

from gtm_agent.notion_client import NotionApiError, NotionClient
from gtm_agent.voice_corpus import append_article, append_tweet
from gtm_agent.x_client import (
    ArticlePublishError,
    ThreadPostError,
    XApiError,
    get_authenticated_user_id,
    post_article,
    post_thread,
    post_tweet,
    retweet,
    tweet_id_from_url,
)

THREAD_SEPARATOR_RE = re.compile(r"\n\s*---\s*\n")
MAX_TWEET_CHARS = 280

IMPLEMENTED_TYPES = {"single-thread", "multi-thread", "article"}


class ThreadValidationError(RuntimeError):
    pass


def parse_thread(text: str) -> list[str]:
    parts = THREAD_SEPARATOR_RE.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


def validate_thread(tweets: list[str]) -> None:
    if not tweets:
        raise ThreadValidationError(
            "Thread has no tweets after parsing (empty or malformed separators)."
        )
    too_long = [
        (i + 1, len(t)) for i, t in enumerate(tweets) if len(t) > MAX_TWEET_CHARS
    ]
    if too_long:
        details = ", ".join(f"tweet {i} ({n} chars)" for i, n in too_long)
        raise ThreadValidationError(
            f"Thread has {len(too_long)} tweet(s) over {MAX_TWEET_CHARS} chars: {details}"
        )


def post_row(notion: NotionClient, row: dict, access_token: str) -> tuple[bool, str]:
    post_type = row["post_type"]
    if post_type not in IMPLEMENTED_TYPES:
        return (
            False,
            f"Row {row['id']} has post-type '{post_type}', which isn't a known "
            f"type ({', '.join(sorted(IMPLEMENTED_TYPES))}). Skipped, left as-is.",
        )

    text = row["final_text"].strip()
    if not text:
        return False, f"Row {row['id']} has no text to post (Final Text is empty)."

    if post_type == "single-thread":
        return _post_single(notion, row, text, access_token)
    if post_type == "article":
        return _post_article(notion, row, text, access_token)
    return _post_multi_thread(notion, row, text, access_token)


def _post_single(
    notion: NotionClient, row: dict, text: str, access_token: str
) -> tuple[bool, str]:
    if len(text) > MAX_TWEET_CHARS:
        return (
            False,
            f"Row {row['id']} text is {len(text)} chars, over the "
            f"{MAX_TWEET_CHARS} limit for single-thread.",
        )

    try:
        result = post_tweet(text, access_token)
    except XApiError as e:
        return False, _record_error(notion, row["id"], f"Post failed: {e}")

    tweet_id = result["data"]["id"]
    posted_url = f"https://x.com/i/web/status/{tweet_id}"
    return _finish(notion, row["id"], text, "single-thread", tweet_id, posted_url)


def _post_multi_thread(
    notion: NotionClient, row: dict, text: str, access_token: str
) -> tuple[bool, str]:
    try:
        tweets = parse_thread(text)
        validate_thread(tweets)
    except ThreadValidationError as e:
        return False, _record_error(notion, row["id"], str(e))

    try:
        results = post_thread(tweets, access_token)
    except ThreadPostError as e:
        message = (
            f"{e} Posted tweet IDs: {e.posted_tweet_ids} — LIVE on X, not rolled "
            "back. Needs manual cleanup or continuation; not auto-retrying to "
            "avoid duplicating the successful prefix."
        )
        return False, _record_error(notion, row["id"], message)

    first_tweet_id = results[0]["data"]["id"]
    posted_url = f"https://x.com/i/web/status/{first_tweet_id}"
    return _finish(
        notion, row["id"], text, "multi-thread", first_tweet_id, posted_url
    )


def resolve_article_title(title_property: str, text: str) -> tuple[str, str]:
    """Return (title, body) for an article.

    The Title property is the intended source. If it's empty, fall back to the
    older convention of taking the first line of Final Text as the title — the
    line is then dropped from the body so it doesn't appear twice."""
    title = title_property.strip()
    if title:
        return title, text.strip()

    lines = text.split("\n")
    fallback_title = lines[0].strip()
    body = "\n".join(lines[1:]).strip()

    if not fallback_title:
        raise ThreadValidationError(
            "Article has no Title and Final Text starts blank — set the Title "
            "property, or put the title on the first line of Final Text."
        )
    if not body:
        raise ThreadValidationError(
            "Article has no Title property and only one line of Final Text, so "
            "there's a title but no body. Set the Title property and put the "
            "article body in Final Text."
        )
    return fallback_title, body


def _post_article(
    notion: NotionClient, row: dict, text: str, access_token: str
) -> tuple[bool, str]:
    try:
        title, body = resolve_article_title(row.get("title", ""), text)
    except ThreadValidationError as e:
        return False, _record_error(notion, row["id"], str(e))

    try:
        result = post_article(title, body, access_token)
    except ArticlePublishError as e:
        message = (
            f"{e} (draft id: {e.draft_id}) Not auto-retrying — a retry would "
            "create a second draft rather than publish this one."
        )
        return False, _record_error(notion, row["id"], message)
    except XApiError as e:
        return False, _record_error(notion, row["id"], f"Article post failed: {e}")

    article_id = result["data"]["id"]
    posted_url = f"https://x.com/i/web/status/{article_id}"

    try:
        notion.mark_posted(row["id"])
    except NotionApiError as e:
        append_article(body, title=title, tweet_id=article_id, posted_url=posted_url)
        return True, f"Published article ({posted_url}) but failed to update Notion: {e}"

    append_article(body, title=title, tweet_id=article_id, posted_url=posted_url)
    return True, f"Published article: {posted_url}"


def _finish(
    notion: NotionClient,
    page_id: str,
    text: str,
    post_type: str,
    tweet_id: str,
    posted_url: str,
) -> tuple[bool, str]:
    try:
        notion.mark_posted(page_id)
    except NotionApiError as e:
        append_tweet(text, post_type=post_type, tweet_id=tweet_id, posted_url=posted_url)
        return True, f"Posted ({posted_url}) but failed to update Notion: {e}"

    append_tweet(text, post_type=post_type, tweet_id=tweet_id, posted_url=posted_url)
    return True, f"Posted: {posted_url}"


def _record_error(notion: NotionClient, page_id: str, message: str) -> str:
    try:
        notion.set_post_error(page_id, message)
        return message
    except NotionApiError as notion_err:
        return f"{message} (also failed to record Post Error in Notion: {notion_err})"


REPLY_FIELDS = {"Reply 1", "Reply 2", "Reply 3", "Self-Written Reply"}


def post_response_calendar_row(
    notion: NotionClient, row: dict, access_token: str
) -> tuple[bool, str]:
    """Post a Response Calendar row's chosen engagement: a reply, a plain
    retweet, or a quote-retweet (Retweet Message set). `Selected` decides
    which; there's no Like path — that action was cut entirely."""
    selected = row.get("selected")
    tweet_id = tweet_id_from_url(row["url"] or "")
    if not tweet_id:
        return False, _record_error(
            notion,
            row["id"],
            f"Row {row['id']} has no usable Original Tweet URL to reply/retweet to.",
        )

    if selected in REPLY_FIELDS:
        return _post_reply(notion, row, tweet_id, access_token)
    if selected == "Retweet":
        return _post_retweet(notion, row, tweet_id, access_token)
    return (
        False,
        f"Row {row['id']} has Selected={selected!r}, which this script doesn't "
        "post (expected a reply field or Retweet). Skipped, left as-is.",
    )


def _post_reply(
    notion: NotionClient, row: dict, tweet_id: str, access_token: str
) -> tuple[bool, str]:
    text = NotionClient.selected_reply_text(row).strip()
    if not text:
        return False, _record_error(
            notion, row["id"], f"Row {row['id']} has no text in its selected reply field."
        )
    if len(text) > MAX_TWEET_CHARS:
        return False, _record_error(
            notion,
            row["id"],
            f"Row {row['id']} reply is {len(text)} chars, over the {MAX_TWEET_CHARS} limit.",
        )

    try:
        result = post_tweet(text, access_token, reply_to_tweet_id=tweet_id)
    except XApiError as e:
        return False, _record_error(notion, row["id"], f"Reply failed: {e}")

    new_id = result["data"]["id"]
    posted_url = f"https://x.com/i/web/status/{new_id}"
    return _finish_response_row(notion, row["id"], text, "reply", new_id, posted_url)


def _post_retweet(
    notion: NotionClient, row: dict, tweet_id: str, access_token: str
) -> tuple[bool, str]:
    message = row["retweet_message"].strip()

    if message:
        try:
            result = post_tweet(message, access_token, quote_tweet_id=tweet_id)
        except XApiError as e:
            return False, _record_error(notion, row["id"], f"Quote-retweet failed: {e}")
        new_id = result["data"]["id"]
        posted_url = f"https://x.com/i/web/status/{new_id}"
        return _finish_response_row(
            notion, row["id"], message, "quote", new_id, posted_url
        )

    try:
        user_id = get_authenticated_user_id(access_token)
        retweet(user_id, tweet_id, access_token)
    except XApiError as e:
        return False, _record_error(notion, row["id"], f"Retweet failed: {e}")

    try:
        notion.mark_response_row_posted(row["id"])
    except NotionApiError as e:
        return True, f"Retweeted (no message, nothing to learn from) but failed to update Notion: {e}"
    return True, "Retweeted (no message, nothing to learn from)."


def _finish_response_row(
    notion: NotionClient,
    page_id: str,
    text: str,
    post_type: str,
    tweet_id: str,
    posted_url: str,
) -> tuple[bool, str]:
    try:
        notion.mark_response_row_posted(page_id)
    except NotionApiError as e:
        append_tweet(text, post_type=post_type, tweet_id=tweet_id, posted_url=posted_url)
        return True, f"Posted ({posted_url}) but failed to update Notion: {e}"

    append_tweet(text, post_type=post_type, tweet_id=tweet_id, posted_url=posted_url)
    return True, f"Posted: {posted_url}"
