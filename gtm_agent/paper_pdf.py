"""Corresponding-author emails printed in a paper's own PDF — not a guess or
a third-party lookup, the paper states these itself, usually as a footnote
on page 1 like `{jasonwei,dennyzhou}@google.com` or `alice@mit.edu`.

Attribution back to a specific author is done by exact match only: the email
local-part, stripped to letters, must equal the author's name stripped to
letters. A loose/partial match would risk pinning the wrong person's email on
someone who happens to share initials, so anything less than exact is
dropped rather than guessed.
"""

import re

import requests

TIMEOUT_SECONDS = 20
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
BRACE_EMAIL_PATTERN = re.compile(r"\{([\w.+-]+(?:\s*,\s*[\w.+-]+)*)\}@([\w.-]+\.\w+)")
NAME_STRIP = re.compile(r"[^a-z]")


def _normalize(text: str) -> str:
    return NAME_STRIP.sub("", text.lower())


def _extract_emails(text: str) -> list[str]:
    emails = []
    for match in BRACE_EMAIL_PATTERN.finditer(text):
        domain = match.group(2)
        emails.extend(f"{local.strip()}@{domain}" for local in match.group(1).split(","))
    # Strip brace groups first so the plain-email pattern doesn't also catch
    # the tail of `{a,b}@domain` as a bogus `b@domain`-only partial match.
    remainder = BRACE_EMAIL_PATTERN.sub("", text)
    emails.extend(EMAIL_PATTERN.findall(remainder))
    return emails


def find_author_emails(arxiv_id: str, author_names: list[str]) -> dict[str, str]:
    """Returns {author_name: email} for authors whose name exactly matches an
    email's local-part. Authors not printed with an email are simply absent
    from the result, not guessed at."""
    try:
        response = requests.get(f"https://arxiv.org/pdf/{arxiv_id}", timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException:
        return {}

    try:
        from pypdf import PdfReader
        from io import BytesIO

        reader = PdfReader(BytesIO(response.content))
        text = reader.pages[0].extract_text()
    except Exception:
        return {}

    emails = _extract_emails(text)
    normalized_emails = {_normalize(email.split("@")[0]): email for email in emails}

    matches = {}
    for name in author_names:
        key = _normalize(name)
        if key in normalized_emails:
            matches[name] = normalized_emails[key]
    return matches
