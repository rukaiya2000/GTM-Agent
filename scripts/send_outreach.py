"""Run 2 of the workflow: draft (if needed) and send outreach messages, for
authors you've already picked a channel for.

Run 1 (fetch_paper_authors.py) populates authors, handles, and the paper
Blurb automatically. Between run 1 and this: in Notion, check `Selected` on
whoever you want to reach, set `Send Via` (Email/X/LinkedIn) per author, and
edit the Blurb or write directly into Message if you want to change anything
before it goes out. Then run this.

For each paper: drafts one Message per channel (Email/X/LinkedIn) — not per
author — for anyone Selected with a Send Via set and no Message yet. If you
already wrote/edited a Message by hand, that's used as-is and never
overwritten. Drafts pull tone from your own already-sent messages as
few-shot examples, so they converge toward your voice over time.

Then attempts to actually send. X sends a real DM if a valid OAuth token
(dm.write scope — run x_oauth_login.py after pulling this change) and the
author's X Handle are both available. Email sends via Gmail if a valid OAuth
token (run gmail_oauth_login.py) and the author's Email are both available.
LinkedIn is still a stub — it has no third-party send API at all, ever, so
it always drafts and prints for you to copy-paste, and Status stays
"Message Drafted" rather than "Sent".

For Email and X, a successful send also records First Sent/Last Sent and (for
Email) the Gmail thread id, which is what send_followups.py uses afterwards to
check for a reply and, if there isn't one, send up to two follow-ups.

    python scripts/send_outreach.py
"""

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
from gtm_agent.gmail_client import GmailApiError, send_email
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
    channel: str, message: str, email: str, x_handle: str, x_access_token: str | None, gmail_access_token: str | None
) -> tuple[bool, str, str | None]:
    """Returns (sent, note, thread_ref). thread_ref is the Gmail thread id for
    Email sends (needed by send_followups.py to reply in-thread and check for
    a reply); None otherwise."""
    if channel == "Email":
        if not gmail_access_token:
            return False, "Gmail isn't connected yet (run gmail_oauth_login.py) — copy the message above and send it yourself.", None
        if not email:
            return False, "No Email on file for this author — copy the message above and send it yourself.", None
        try:
            result = send_email(email, message, gmail_access_token)
        except GmailApiError as e:
            return False, f"Gmail send failed ({e}) — copy the message above and send it yourself.", None
        return True, f"Sent via Gmail to {email}.", result.get("threadId")
    if channel == "X":
        if not x_access_token:
            return False, "X isn't connected yet (run x_oauth_login.py) — copy the message above and send it yourself.", None
        if not x_handle:
            return False, "No X Handle on file for this author — copy the message above and send it yourself.", None
        try:
            send_dm(x_handle, message, x_access_token)
        except XApiError as e:
            return False, f"X send failed ({e}) — copy the message above and send it yourself.", None
        return True, f"Sent via X DM to {x_handle}.", None
    if channel == "LinkedIn":
        return False, "LinkedIn has no send API — copy the message above and send it yourself.", None
    return False, f"Unknown channel {channel!r}.", None


def send_for_paper(
    notion: NotionClient,
    authors_db_id: str,
    paper_row: dict,
    tone_examples: list[str],
    x_access_token: str | None,
    gmail_access_token: str | None,
) -> None:
    if not paper_row["blurb"]:
        print("  No Blurb yet — run fetch_paper_authors.py first.")
        return

    authors = notion.get_paper_author_rows(authors_db_id, paper_row["id"])
    selected = [a for a in authors if a["selected"] and a["send_via"]]
    if not selected:
        print("  No authors both Selected and with a Send Via set in Notion — do that first, then re-run.")
        return

    to_draft = [a for a in selected if not a["message"]]
    by_channel: dict[str, list[dict]] = {}
    for a in to_draft:
        by_channel.setdefault(a["send_via"], []).append(a)

    for channel, group in by_channel.items():
        try:
            message = outreach_message(paper_blurb_text=paper_row["blurb"], channel=channel, tone_examples=tone_examples)
        except OutreachLLMError as e:
            print(f"  {channel}: drafting failed: {e}")
            continue
        for a in group:
            notion.set_author_message(a["id"], message, status="Message Drafted")
            a["message"] = message  # so the send step below sees it without a re-fetch

    for author in selected:
        if author["status"] == "Sent":
            continue  # already sent — never resend on a re-run
        if not author["message"]:
            continue  # drafting failed above, already reported
        sent, note, thread_ref = attempt_send(
            author["send_via"], author["message"], author["email"] or "", author["x_handle"],
            x_access_token, gmail_access_token,
        )
        status = "Sent" if sent else "Message Drafted"
        notion.set_author_message(author["id"], author["message"], status=status)
        if sent:
            notion.record_initial_send(author["id"], thread_ref, date.today().isoformat())
        print(f"  {author['name']} ({author['send_via']}, {status}):\n    {author['message']}\n    -> {note}\n")


def main() -> int:
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

    x_access_token = get_x_access_token()
    if not x_access_token:
        print("(X not connected — run scripts/x_oauth_login.py to enable real DM sending)\n")

    gmail_access_token = get_gmail_access_token()
    if not gmail_access_token:
        print("(Gmail not connected — run scripts/gmail_oauth_login.py to enable real email sending)\n")

    for paper_row in papers:
        print(f"\n{paper_row['name']}")
        send_for_paper(notion, authors_db_id, paper_row, tone_examples, x_access_token, gmail_access_token)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
