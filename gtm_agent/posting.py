import re
from datetime import datetime

from gtm_agent.notion_client import NotionApiError, NotionClient
from gtm_agent.typefully_client import TypefullyApiError, create_draft
from gtm_agent.voice_corpus import append_article
from gtm_agent.x_client import (
    ArticlePublishError,
    XApiError,
    get_authenticated_user_id,
    post_article,
    retweet,
    tweet_id_from_url,
)

THREAD_SEPARATOR_RE = re.compile(r"\n\s*---\s*\n")
MAX_TWEET_CHARS = 280

# single-thread/multi-thread post through Typefully (push_row_to_typefully);
# article isn't a Typefully format, so it stays on the direct X API (post_row).
TYPEFULLY_TYPES = {"single-thread", "multi-thread"}
DIRECT_API_TYPES = {"article"}
IMPLEMENTED_TYPES = TYPEFULLY_TYPES | DIRECT_API_TYPES


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


def push_row_to_typefully(notion: NotionClient, row: dict) -> tuple[bool, str]:
    """Push a Tweet Drafts row (single-thread/multi-thread, Ready to post,
    Typefully Draft ID still empty) to Typefully. On success, sets Stage to
    'Scheduled' — sync_typefully_status.py flips it to Posted once Typefully
    actually publishes at the scheduled time."""
    post_type = row["post_type"]
    if post_type not in TYPEFULLY_TYPES:
        return (
            False,
            f"Row {row['id']} has post-type '{post_type}', not Typefully-eligible "
            f"({', '.join(sorted(TYPEFULLY_TYPES))}). Skipped, left as-is.",
        )

    text = row["final_text"].strip()
    if not text:
        return False, f"Row {row['id']} has no text to post (Final Text is empty)."

    if post_type == "single-thread":
        if len(text) > MAX_TWEET_CHARS:
            return False, _record_error(
                notion,
                row["id"],
                f"Row {row['id']} text is {len(text)} chars, over the "
                f"{MAX_TWEET_CHARS} limit for single-thread.",
            )
        posts = [text]
    else:
        try:
            posts = parse_thread(text)
            validate_thread(posts)
        except ThreadValidationError as e:
            return False, _record_error(notion, row["id"], str(e))

    publish_at = _typefully_publish_at(row.get("scheduled_time") or "")
    try:
        draft_id = create_draft(posts, publish_at=publish_at, draft_title=row.get("title") or None)
    except TypefullyApiError as e:
        return False, _record_error(notion, row["id"], f"Typefully push failed: {e}")

    try:
        notion.set_typefully_draft_id(row["id"], draft_id)
        notion.set_stage(row["id"], "Scheduled")
    except NotionApiError as e:
        return True, f"Pushed to Typefully (draft {draft_id}) but failed to update Notion: {e}"

    return True, f"Pushed to Typefully (draft {draft_id}), scheduled for {publish_at}. Stage set to Scheduled."


def post_row(notion: NotionClient, row: dict, access_token: str) -> tuple[bool, str]:
    """Direct-X-API posting — now only for post-types Typefully can't do
    (Articles). single-thread/multi-thread go through push_row_to_typefully
    instead."""
    post_type = row["post_type"]
    if post_type not in DIRECT_API_TYPES:
        return (
            False,
            f"Row {row['id']} has post-type '{post_type}', which this direct-API "
            f"path doesn't post ({', '.join(sorted(DIRECT_API_TYPES))} only — "
            f"{', '.join(sorted(TYPEFULLY_TYPES))} go through Typefully). Skipped, left as-is.",
        )

    text = row["final_text"].strip()
    if not text:
        return False, f"Row {row['id']} has no text to post (Final Text is empty)."

    return _post_article(notion, row, text, access_token)


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


def _typefully_publish_at(scheduled_time: str) -> str:
    """Typefully requires publish_at to be a timezone-aware datetime (or the
    literal "now"/"next-free-slot") and rejects naive or past values. Notion
    dates arrive date-only or naive — treat those as local time — and a time
    that's already due becomes "now"."""
    if not scheduled_time:
        return "now"
    try:
        when = datetime.fromisoformat(scheduled_time)
    except ValueError:
        return "now"
    if when.tzinfo is None:
        when = when.astimezone()
    if when <= datetime.now().astimezone():
        return "now"
    return when.isoformat()


def _record_error(notion: NotionClient, page_id: str, message: str) -> str:
    try:
        notion.set_post_error(page_id, message)
        return message
    except NotionApiError as notion_err:
        return f"{message} (also failed to record Post Error in Notion: {notion_err})"


REPLY_FIELDS = {"Reply 1", "Reply 2", "Reply 3", "Self-Written Reply"}


def push_response_row_to_typefully(notion: NotionClient, row: dict) -> tuple[bool, str]:
    """Push a Response Calendar reply row to Typefully via reply_to_url. On
    success, sets Status to 'Scheduled' — sync_typefully_status.py flips it
    to Posted once Typefully actually publishes."""
    selected = row.get("selected")
    if selected not in REPLY_FIELDS:
        return (
            False,
            f"Row {row['id']} has Selected={selected!r}, not a reply field — not "
            "Typefully-eligible. Skipped, left as-is.",
        )

    if not (row["url"] or "").strip():
        return False, _record_error(
            notion, row["id"], f"Row {row['id']} has no Original Tweet URL to reply to."
        )

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

    publish_at = _typefully_publish_at(row.get("scheduled_time") or "")
    try:
        draft_id = create_draft([text], publish_at=publish_at, reply_to_url=row["url"])
    except TypefullyApiError as e:
        return False, _record_error(notion, row["id"], f"Typefully push failed: {e}")

    try:
        notion.set_typefully_draft_id(row["id"], draft_id)
        notion.set_response_status(row["id"], "Scheduled")
    except NotionApiError as e:
        return True, f"Pushed reply to Typefully (draft {draft_id}) but failed to update Notion: {e}"

    return True, f"Pushed reply to Typefully (draft {draft_id}), scheduled for {publish_at}. Status set to Scheduled."


def post_response_calendar_row(
    notion: NotionClient, row: dict, access_token: str
) -> tuple[bool, str]:
    """Direct-X-API posting — now only for a plain retweet
    (Selected='Retweet'). Reply rows go through
    push_response_row_to_typefully instead."""
    selected = row.get("selected")
    tweet_id = tweet_id_from_url(row["url"] or "")
    if not tweet_id:
        return False, _record_error(
            notion,
            row["id"],
            f"Row {row['id']} has no usable Original Tweet URL to retweet.",
        )

    if selected == "Retweet":
        return _post_retweet(notion, row, tweet_id, access_token)
    return (
        False,
        f"Row {row['id']} has Selected={selected!r}, which this direct-API path "
        "doesn't post (expected Retweet — reply fields go through Typefully). "
        "Skipped, left as-is.",
    )


def _post_retweet(
    notion: NotionClient, row: dict, tweet_id: str, access_token: str
) -> tuple[bool, str]:
    # Quote-retweeting is gone: X withdrew quote-posting (and API replies to
    # posts that don't mention this account) from all self-serve tiers in
    # 2026, and Premium doesn't restore it. A leftover Retweet Message is
    # human-approved text that can no longer go out — refuse rather than
    # silently repost without it.
    message = row["retweet_message"].strip()
    if message:
        return False, _record_error(
            notion,
            row["id"],
            "This row has a Retweet Message, but X removed quote-posting from "
            "self-serve API tiers — clear Retweet Message to plain-repost, or "
            "post the quote by hand.",
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
