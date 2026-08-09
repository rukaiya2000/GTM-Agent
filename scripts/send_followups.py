"""Run 3 (recurring) of the outreach workflow: check whether anyone who was
sent an outreach message has replied and, if not, send follow-ups on a
schedule.

Every run, for each Email/X author in Status Sent, Followup 1 Sent, or
Followup 2 Sent:

  1. Check for a reply first, regardless of timing. If there is one, Status
     becomes Replied and nothing is ever sent to that author again.
  2. Otherwise, if enough time has passed since the last message, send the
     next follow-up: Follow-up 1 fires OUTREACH_FOLLOWUP1_DAYS (default 6)
     after the initial message; Follow-up 2 fires OUTREACH_FOLLOWUP2_DAYS
     (default 10) after Follow-up 1 — both counted from the *previous* send,
     not from the original message, and both configurable in .env. After
     Follow-up 2, this script only checks for replies; it never sends a third
     message.

Follow-ups are drafted with outreach_llm.followup_message(), which nudges
rather than re-pitches, and reuses the same Sent-message tone examples as
send_outreach.py.

Email replies are checked by looking at the Gmail thread (requires the
gmail.readonly scope — re-run gmail_oauth_login.py if your saved token
predates it) and sent as a reply in that same thread. X replies are checked
via the DM conversation (requires the dm.read scope — re-run
x_oauth_login.py if your saved token predates it). LinkedIn has neither a
send nor a read API, so those rows are left alone; check replies there
yourself.

    python scripts/send_followups.py
    python scripts/send_followups.py --dry-run    # preview without sending or updating Notion
"""

import argparse
from datetime import date

from gtm_agent.config import (
    ConfigError,
    get_followup1_days,
    get_followup2_days,
    get_gmail_client_id,
    get_gmail_client_secret,
    get_paper_authors_db_id,
    get_x_client_id,
    get_x_client_secret,
)
from gtm_agent.gmail_client import GmailApiError, get_profile, send_email, split_subject_and_body, thread_has_reply
from gtm_agent.gmail_oauth import get_valid_access_token as get_valid_gmail_token
from gtm_agent.notion_client import NotionApiError, NotionClient
from gtm_agent.outreach_llm import OutreachLLMError, followup_message
from gtm_agent.x_client import (
    XApiError,
    XClient,
    conversation_has_reply,
    get_authenticated_user_id,
    resolve_participant_id,
    send_dm,
)
from gtm_agent.x_oauth import get_valid_access_token as get_valid_x_token

ACTIONABLE_STATUSES = ("Sent", "Followup 1 Sent", "Followup 2 Sent")
AUTOMATABLE_CHANNELS = ("Email", "X")
NEXT_FOLLOWUP = {"Sent": 1, "Followup 1 Sent": 2}
FOLLOWUP_STATUS = {1: "Followup 1 Sent", 2: "Followup 2 Sent"}


def get_x_access_token() -> str | None:
    try:
        return get_valid_x_token(get_x_client_id(), get_x_client_secret())
    except ConfigError:
        return None


def get_gmail_access_token() -> str | None:
    try:
        return get_valid_gmail_token(get_gmail_client_id(), get_gmail_client_secret())
    except ConfigError:
        return None


def days_since(iso_date: str) -> int:
    return (date.today() - date.fromisoformat(iso_date)).days


def check_replied(
    author: dict, gmail_token: str | None, gmail_own_email: str | None, x_client: XClient | None, x_token: str | None, own_x_id: str | None
) -> bool:
    try:
        if author["send_via"] == "Email" and author["thread_ref"] and gmail_token and gmail_own_email:
            return thread_has_reply(author["thread_ref"], gmail_own_email, gmail_token)
        if author["send_via"] == "X" and author["x_handle"] and x_client and x_token and own_x_id:
            participant_id = resolve_participant_id(x_client, author["x_handle"])
            if participant_id:
                return conversation_has_reply(participant_id, own_x_id, x_token)
    except (GmailApiError, XApiError) as e:
        print(f"  reply check failed ({e}) — leaving status as is")
    return False


def send_followup(author: dict, message: str, gmail_token: str | None, x_token: str | None) -> tuple[bool, str]:
    if author["send_via"] == "Email":
        if not gmail_token:
            return False, "Gmail isn't connected — copy the message above and send it yourself."
        original_subject, _ = split_subject_and_body(author["message"])
        try:
            send_email(
                author["email"] or "", message, gmail_token,
                thread_id=author["thread_ref"] or None, subject_override=f"Re: {original_subject}",
            )
        except GmailApiError as e:
            return False, f"Gmail send failed ({e}) — copy the message above and send it yourself."
        return True, f"Sent via Gmail to {author['email']}."
    if author["send_via"] == "X":
        if not x_token:
            return False, "X isn't connected — copy the message above and send it yourself."
        try:
            send_dm(author["x_handle"], message, x_token)
        except XApiError as e:
            return False, f"X send failed ({e}) — copy the message above and send it yourself."
        return True, f"Sent via X DM to {author['x_handle']}."
    return False, "Unknown channel."


def process_author(
    notion: NotionClient,
    author: dict,
    tone_examples: list[str],
    delays: dict[int, int],
    gmail_token: str | None,
    gmail_own_email: str | None,
    x_client: XClient | None,
    x_token: str | None,
    own_x_id: str | None,
    dry_run: bool,
) -> None:
    if check_replied(author, gmail_token, gmail_own_email, x_client, x_token, own_x_id):
        print("  replied — stopping follow-ups")
        if not dry_run:
            notion.set_author_status(author["id"], "Replied")
        return

    next_n = NEXT_FOLLOWUP.get(author["status"])
    if next_n is None:
        print("  no reply yet, both follow-ups already sent")
        return

    if not author["last_sent"]:
        print("  no Last Sent on file (sent before follow-ups existed) — skipping")
        return

    elapsed = days_since(author["last_sent"])
    required = delays[next_n]
    if elapsed < required:
        print(f"  no reply yet, {elapsed}/{required} days since last send — not due")
        return

    try:
        message = followup_message(
            previous_message=author["message"], channel=author["send_via"],
            followup_number=next_n, tone_examples=tone_examples,
        )
    except OutreachLLMError as e:
        print(f"  follow-up {next_n} drafting failed: {e}")
        return

    print(f"  follow-up {next_n} draft:\n    {message}")
    if dry_run:
        return

    sent, note = send_followup(author, message, gmail_token, x_token)
    if sent:
        notion.record_followup(author["id"], next_n, message, FOLLOWUP_STATUS[next_n], date.today().isoformat())
    print(f"    -> {note}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending or updating Notion")
    args = parser.parse_args()

    try:
        authors_db_id = get_paper_authors_db_id()
        notion = NotionClient()
    except ConfigError as e:
        print(f"Config error: {e}")
        return 1

    try:
        authors = notion.get_paper_author_rows(authors_db_id)
    except NotionApiError as e:
        print(f"Notion request failed: {e}")
        return 1

    candidates = [a for a in authors if a["status"] in ACTIONABLE_STATUSES and a["send_via"] in AUTOMATABLE_CHANNELS]
    if not candidates:
        print("No sent outreach awaiting a reply check or follow-up.")
        return 0

    gmail_token = get_gmail_access_token()
    if not gmail_token:
        print("(Gmail not connected — run scripts/gmail_oauth_login.py to check/send email follow-ups)\n")
    gmail_own_email = None
    if gmail_token:
        try:
            gmail_own_email = get_profile(gmail_token)["emailAddress"]
        except GmailApiError as e:
            print(f"(Could not read Gmail profile: {e} — re-run gmail_oauth_login.py if this persists)\n")

    x_token = get_x_access_token()
    if not x_token:
        print("(X not connected — run scripts/x_oauth_login.py to check/send X follow-ups)\n")
    x_client = XClient() if any(a["send_via"] == "X" for a in candidates) else None
    own_x_id = None
    if x_token and x_client:
        try:
            own_x_id = get_authenticated_user_id(x_token)
        except XApiError as e:
            print(f"(Could not read own X user id: {e} — re-run x_oauth_login.py if this persists)\n")

    tone_examples = notion.get_sent_messages(authors_db_id)
    delays = {1: get_followup1_days(), 2: get_followup2_days()}

    for author in candidates:
        print(f"\n{author['name']} ({author['send_via']}, {author['status']})")
        process_author(notion, author, tone_examples, delays, gmail_token, gmail_own_email, x_client, x_token, own_x_id, args.dry_run)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
