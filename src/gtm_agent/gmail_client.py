import base64
from email.mime.text import MIMEText

import requests

SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


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


def send_email(to: str, message: str, access_token: str) -> dict:
    """Send an email via the Gmail API. `message` is the full drafted text,
    including its 'Subject: ...' first line."""
    subject, body = split_subject_and_body(message)
    mime = MIMEText(body)
    mime["to"] = to
    mime["subject"] = subject
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()

    response = requests.post(
        SEND_URL,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json={"raw": raw},
    )
    if response.status_code == 401:
        raise GmailApiError(401, "unauthorized — Gmail OAuth token missing/expired/invalid")
    if not response.ok:
        raise GmailApiError(response.status_code, response.text)
    return response.json()
