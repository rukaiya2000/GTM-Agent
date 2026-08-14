import requests

from gtm_agent.config import get_typefully_api_key, get_typefully_social_set_id

BASE_URL = "https://api.typefully.com/v2"


class TypefullyApiError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(f"Typefully API error {status_code}: {message}")
        self.status_code = status_code


def _headers(api_key: str | None) -> dict:
    return {"Authorization": f"Bearer {api_key or get_typefully_api_key()}"}


def _request(method: str, path: str, api_key: str | None, body: dict | None = None) -> dict | None:
    response = requests.request(
        method,
        f"{BASE_URL}{path}",
        headers=_headers(api_key),
        json=body,
    )
    if response.status_code == 401:
        raise TypefullyApiError(401, "unauthorized — check TYPEFULLY_API_KEY")
    if not response.ok:
        raise TypefullyApiError(response.status_code, response.text)
    return response.json() if response.content else None


def create_draft(
    posts: list[str],
    publish_at: str | None = None,
    reply_to_url: str | None = None,
    draft_title: str | None = None,
    social_set_id: str | None = None,
    api_key: str | None = None,
) -> str:
    """Create (and, if publish_at is set, schedule) an X draft. posts is one
    string per tweet — a single-element list posts one tweet, more than one
    builds a thread. publish_at accepts an ISO8601 datetime, "now", or
    "next-free-slot"; omit it to leave the draft unscheduled. Returns the
    Typefully draft id."""
    x_platform: dict = {"enabled": True, "posts": [{"text": text} for text in posts]}
    if reply_to_url:
        x_platform["settings"] = {"reply_to_url": reply_to_url}

    body: dict = {"platforms": {"x": x_platform}}
    if publish_at:
        body["publish_at"] = publish_at
    if draft_title:
        body["draft_title"] = draft_title

    result = _request(
        "POST",
        f"/social-sets/{social_set_id or get_typefully_social_set_id()}/drafts",
        api_key,
        body,
    )
    return str(result["id"])


def get_draft(draft_id: str, social_set_id: str | None = None, api_key: str | None = None) -> dict:
    """Returns the draft's current status ("draft"/"scheduled"/"planned"/
    "publishing"/"published"/"error") plus its published_at and
    x_published_url once live."""
    return _request(
        "GET",
        f"/social-sets/{social_set_id or get_typefully_social_set_id()}/drafts/{draft_id}",
        api_key,
    )
