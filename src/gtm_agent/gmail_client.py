import base64
import re
from email.mime.text import MIMEText

import requests

SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
THREADS_URL = "https://gmail.googleapis.com/gmail/v1/users/me/threads"
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


class GmailApiError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(f"Gmail API error {status_code}: {message}")
        self.status_code = status_code


def split_subject_and_body(message: str) -> tuple[str, str]:
    """outreach_message()'s Email drafts put 'Subject: ...' on the first
    line, per CHANNEL_GUIDANCE. Falls back to a generic subject if a message
    was hand-written in Notion without one."""
    lines = message.split("\n", 1)
    if lines[0].strip().lower().startswith("subject:"):
        subject = lines[0].split(":", 1)[1].strip()
        body = lines[1].lstrip("\n") if len(lines) > 1 else ""
        return subject, body
    return "Following up on your paper", message


def send_email(
    to: str, message: str, access_token: str, thread_id: str | None = None, subject_override: str | None = None
) -> dict:
    """Send an email via the Gmail API. `message` is the full drafted text,
    including its 'Subject: ...' first line — unless `subject_override` is
    given, in which case `message` is the body only and `subject_override`
    is used as-is. Pass `thread_id` (from a prior send's response) together
    with a "Re: ..." `subject_override` to land this as a reply in the same
    Gmail thread, as `send_followups.py` does."""
    if subject_override is not None:
        subject, body = subject_override, message
    else:
        subject, body = split_subject_and_body(message)
    mime = MIMEText(body)
    mime["to"] = to
    mime["subject"] = subject
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()

    body_json: dict = {"raw": raw}
    if thread_id:
        body_json["threadId"] = thread_id

    response = requests.post(
        SEND_URL,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json=body_json,
    )
    if response.status_code == 401:
        raise GmailApiError(401, "unauthorized — Gmail OAuth token missing/expired/invalid")
    if not response.ok:
        raise GmailApiError(response.status_code, response.text)
    return response.json()


def get_profile(access_token: str) -> dict:
    response = requests.get(PROFILE_URL, headers={"Authorization": f"Bearer {access_token}"})
    if response.status_code == 401:
        raise GmailApiError(401, "unauthorized — Gmail OAuth token missing/expired/invalid")
    if not response.ok:
        raise GmailApiError(response.status_code, response.text)
    return response.json()


def thread_has_reply(thread_id: str, own_email: str, access_token: str) -> bool:
    """True if the thread contains a message from anyone other than us.
    Requires the gmail.readonly scope — re-run gmail_oauth_login.py if your
    saved token predates it."""
    response = requests.get(
        f"{THREADS_URL}/{thread_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"format": "metadata", "metadataHeaders": "From"},
    )
    if response.status_code == 401:
        raise GmailApiError(401, "unauthorized — Gmail OAuth token missing/expired/invalid (readonly scope required)")
    if not response.ok:
        raise GmailApiError(response.status_code, response.text)

    own = own_email.strip().lower()
    for msg in response.json().get("messages", []):
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        match = EMAIL_PATTERN.search(headers.get("From", ""))
        if match and match.group(0).lower() != own:
            return True
    return False
