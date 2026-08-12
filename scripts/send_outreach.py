"""Drafts and, on request, sends outreach messages for a paper's authors.

By default (`--draft-only`, which `paper-outreach` always uses right after
fetching/researching authors) this drafts a Subject + Message for every
author who doesn't have one yet and has *some* contact info on file (Email,
X Handle, or LinkedIn). It never touches `Send Via` — that's entirely a
human decision made afterwards in Notion — and it never sends anything.
Every draft is written in Email format (subject + body); which parts
actually get used depends on whatever channel a human later picks (see
below), not on what's drafted.

Without `--draft-only`, this is the deliberate send step (what
`publish-paper-outreach` runs): sends to every author with a `Send Via` set
in Notion — a human picking a channel *is* the authorization, nothing else
is checked. If `Send Via` is Email, the Subject + Message are both used; if
it's X or LinkedIn, only the Message is used and the Subject is dropped.
Anyone with no `Send Via` set is left alone entirely.

Sending: X sends a real DM if a valid OAuth token (dm.write scope — run
x_oauth_login.py) and the author's X Handle are both available. Email sends
via Gmail if a valid OAuth token (run gmail_oauth_login.py) and the author's
Email are both available. LinkedIn is still a stub — it has no third-party
send API at all, ever, so it always drafts and prints for you to copy-paste,
and Status stays "Message Drafted" rather than "Sent".

Whatever went wrong on a failed/skipped send attempt (no OAuth token, no
contact on file, LinkedIn having no send API, an API error) is written to
the `Post Error` column so it's visible directly in Notion, not just in this
script's console output; a later successful send clears it. For Email and X,
a successful send also records First Sent/Last Sent and (for Email) the
Gmail thread id, which is what send_followups.py uses afterwards to check
for a reply and, if there isn't one, send up to two follow-ups.

    python scripts/send_outreach.py --draft-only    # draft only, never sends
    python scripts/send_outreach.py                 # sends to anyone with a Send Via set
"""

import argparse
from datetime import date

from gtm_agent.config import (
    ConfigError,
    get_gmail_client_id,
    get_gmail_client_secret,
    get_paper_authors_db_id,
    get_paper_outreach_db_id,
    get_x_client_id,
    get_x_client_secret,
)
from gtm_agent.gmail_client import GmailApiError, send_email, split_subject_and_body
from gtm_agent.gmail_oauth import get_valid_access_token as get_valid_gmail_token
from gtm_agent.notion_client import NotionApiError, NotionClient
from gtm_agent.outreach_llm import OutreachLLMError, outreach_message
from gtm_agent.x_client import XApiError, send_dm
from gtm_agent.x_oauth import get_valid_access_token as get_valid_x_token

READY_STATUSES = ("Needs Review", "Blurb Ready")


def get_x_access_token() -> str | None:
    """None if X isn't connected — callers fall back to drafting only."""
    try:
        return get_valid_x_token(get_x_client_id(), get_x_client_secret())
    except ConfigError:
        return None


def get_gmail_access_token() -> str | None:
    """None if Gmail isn't connected — callers fall back to drafting only."""
    try:
        return get_valid_gmail_token(get_gmail_client_id(), get_gmail_client_secret())
    except ConfigError:
        return None


def attempt_send(
    channel: str,
    message: str,
    email: str,
    x_handle: str,
    x_access_token: str | None,
    gmail_access_token: str | None,
    subject: str = "",
) -> tuple[bool, str, str | None]:
    """Returns (sent, note, thread_ref). thread_ref is the Gmail thread id for
    Email sends (needed by send_followups.py to reply in-thread and check for
    a reply); None otherwise. `subject` is Email-only; other channels ignore
    it. `note` is written to Notion's Post Error column on failure, so it's
    kept generic rather than console-specific."""
    if channel == "Email":
        if not gmail_access_token:
            return False, "Gmail isn't connected (run gmail_oauth_login.py).", None
        if not email:
            return False, "No Email on file for this author.", None
        try:
            result = send_email(email, message, gmail_access_token, subject_override=subject or "Following up on your paper")
        except GmailApiError as e:
            return False, f"Gmail send failed: {e}", None
        return True, f"Sent via Gmail to {email}.", result.get("threadId")
    if channel == "X":
        if not x_access_token:
            return False, "X isn't connected (run x_oauth_login.py).", None
        if not x_handle:
            return False, "No X Handle on file for this author.", None
        try:
            send_dm(x_handle, message, x_access_token)
        except XApiError as e:
            return False, f"X send failed: {e}", None
        return True, f"Sent via X DM to {x_handle}.", None
    if channel == "LinkedIn":
        return False, "LinkedIn has no send API — copy the Message column and send manually.", None
    return False, f"Unknown channel {channel!r}.", None


def draft_messages(
    notion: NotionClient,
    paper_row: dict,
    authors: list[dict],
    tone_examples: list[str],
) -> None:
    """Drafts a Subject + Message for every author in `authors` that doesn't
    have one yet and has some contact info on file (Email, X Handle, or
    LinkedIn) — anyone with none of those is skipped and reported, since
    there'd be nothing to ever send it through. Always drafted in Email
    format (subject + body); which parts get used at send time depends on
    whatever `Send Via` a human later picks, not on this. Never touches
    `Send Via`. Never sends anything."""
    to_draft = [a for a in authors if not a["message"] and (a["email"] or a["x_handle"] or a["linkedin"])]
    for a in authors:
        if not a["message"] and not (a["email"] or a["x_handle"] or a["linkedin"]):
            print(f"  {a['name']}: no Email/X Handle/LinkedIn on file — nothing to draft against.")

    if not to_draft:
        return

    try:
        draft = outreach_message(paper_blurb_text=paper_row["blurb"], channel="Email", tone_examples=tone_examples)
    except OutreachLLMError as e:
        print(f"  drafting failed: {e}")
        return

    subject, body = split_subject_and_body(draft)
    for a in to_draft:
        notion.set_author_message(a["id"], body, status="Message Drafted", subject=subject)
        a["message"] = body  # so a later step sees it without a re-fetch
        a["subject"] = subject
        print(f"  {a['name']}: drafted\n    Subject: {subject}\n    {body}\n")


def send_for_paper(
    notion: NotionClient,
    authors_db_id: str,
    paper_row: dict,
    tone_examples: list[str],
    x_access_token: str | None,
    gmail_access_token: str | None,
    draft_only: bool,
) -> None:
    if not paper_row["blurb"]:
        print("  No Blurb yet — run fetch_paper_authors.py first.")
        return

    authors = notion.get_paper_author_rows(authors_db_id, paper_row["id"])

    if draft_only:
        draft_messages(notion, paper_row, [a for a in authors if a["status"] != "Sent"], tone_examples)
        return

    # A human picking a Send Via channel is the sole authorization to reach
    # out — nothing else (e.g. Selected) is checked.
    to_send = [a for a in authors if a["send_via"]]
    if not to_send:
        print("  No authors have a Send Via set in Notion — do that first, then re-run.")
        return

    draft_messages(notion, paper_row, [a for a in to_send if not a["message"]], tone_examples)

    for author in to_send:
        if author["status"] == "Sent":
            continue  # already sent — never resend on a re-run
        if not author["message"]:
            continue  # drafting failed above, already reported
        channel = author["send_via"]
        subject = author.get("subject") or "" if channel == "Email" else ""
        sent, note, thread_ref = attempt_send(
            channel, author["message"], author["email"] or "", author["x_handle"],
            x_access_token, gmail_access_token, subject=subject,
        )
        if sent:
            notion.set_author_message(author["id"], author["message"], status="Sent", post_error="")
            notion.record_initial_send(author["id"], thread_ref, date.today().isoformat())
        else:
            notion.set_author_message(author["id"], author["message"], status="Message Drafted", post_error=note)
        status = "Sent" if sent else "Message Drafted"
        print(f"  {author['name']} ({channel}, {status}): -> {note}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--draft-only", action="store_true",
        help="Draft Subject/Message for every author with a contact on file. Never touches Send Via, never sends.",
    )
    args = parser.parse_args()

    try:
        paper_db_id = get_paper_outreach_db_id()
        authors_db_id = get_paper_authors_db_id()
        notion = NotionClient()
    except ConfigError as e:
        print(f"Config error: {e}")
        return 1

    try:
        papers = []
        for status in READY_STATUSES:
            papers += notion.get_paper_outreach_rows(paper_db_id, status=status)
    except NotionApiError as e:
        print(f"Notion request failed: {e}")
        return 1

    if not papers:
        print("No papers ready (need authors + blurb fetched first — run fetch_paper_authors.py).")
        return 0

    tone_examples = notion.get_sent_messages(authors_db_id)
    if not tone_examples:
        print("(no Sent messages yet to draw tone from — drafts will be plain until you've sent a few)\n")

    x_access_token = None
    gmail_access_token = None
    if not args.draft_only:
        x_access_token = get_x_access_token()
        if not x_access_token:
            print("(X not connected — run scripts/x_oauth_login.py to enable real DM sending)\n")

        gmail_access_token = get_gmail_access_token()
        if not gmail_access_token:
            print("(Gmail not connected — run scripts/gmail_oauth_login.py to enable real email sending)\n")

    for paper_row in papers:
        print(f"\n{paper_row['name']}")
        send_for_paper(
            notion, authors_db_id, paper_row, tone_examples, x_access_token, gmail_access_token,
            draft_only=args.draft_only,
        )

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
