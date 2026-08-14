"""Drafts and, on request, sends outreach messages for a paper's authors.

By default (`--draft-only`, which `paper-outreach` always uses right after
fetching/researching authors) this drafts a Subject + Message for every
author who doesn't have one yet and has *some* contact info on file (Email,
X Handle, or LinkedIn). It never touches `Send Via` — that's entirely a
human decision made afterwards in Notion — and it never sends anything.
Every draft is written in Email format (subject + body); which parts
actually get used depends on whatever channel a human later picks (see
below), not on what's drafted. Anyone with a LinkedIn URL on file
additionally gets a `LinkedIn Note` drafted — a separate, much shorter
format (200-char hard cap, LinkedIn's own limit on connection-request
notes), not a reuse of Message.

Without `--draft-only`, this is the deliberate send step (what
`publish-paper-outreach` runs): sends to every author with a `Send Via` set
in Notion — a human picking a channel *is* the authorization, nothing else
is checked. If `Send Via` is Email, the Subject + Message are both used; if
it's X, only the Message is used and the Subject is dropped; if it's
LinkedIn, the `LinkedIn Note` field is what matters, not Message.
Anyone with no `Send Via` set is left alone entirely.

Sending: X sends a real DM if a valid OAuth token (dm.write scope — run
x_oauth_login.py) and the author's X Handle are both available. Email sends
via Gmail if a valid OAuth token (run gmail_oauth_login.py) and the author's
Email are both available. LinkedIn is deliberately never sent for you —
there is no official API for sending a LinkedIn connection request, and the
unofficial ones require your raw LinkedIn password and risk the account
being restricted, so this always drafts the note and prints it for you to
paste into the connection request by hand; Status stays "Message Drafted"
rather than "Sent".

Whatever went wrong on a failed/skipped send attempt (no OAuth token, no
contact on file, LinkedIn having no send API, an API error) is written to
the `Post Error` column so it's visible directly in Notion, not just in this
script's console output; a later successful send clears it. For Email and X,
a successful send also records First Sent/Last Sent and (for Email) the
Gmail thread id, which is what send_followups.py uses afterwards to check
for a reply and, if there isn't one, send up to two follow-ups.

    python gtm_agent/send_outreach.py --draft-only    # draft only, never sends
    python gtm_agent/send_outreach.py                 # sends to anyone with a Send Via set
"""

import argparse
from datetime import date, datetime, timezone

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


def is_due(author: dict) -> bool:
    """True if the author has no Scheduled Time (send now, same as before
    this field existed) or it's already in the past. False for a future
    Scheduled Time — skipped until a later run."""
    scheduled_time = author.get("scheduled_time")
    if not scheduled_time:
        return True
    dt = datetime.fromisoformat(scheduled_time.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt < datetime.now(timezone.utc)


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
        if not message:
            return False, "No LinkedIn Note drafted yet for this author.", None
        return (
            False,
            "LinkedIn sends run through the LinkedIn automation tool, not this "
            "script — run gtm_agent/export_linkedin_leads.py to get this "
            "author's CSV + notes for the campaign.",
            None,
        )
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

    # LinkedIn's connection note is a separate, much shorter format than the
    # email draft above (200-char hard cap, LinkedIn's own limit on connection
    # notes) — drafted independently, into its own field, for anyone with a
    # LinkedIn URL on file who doesn't have one yet.
    to_draft_linkedin = [a for a in authors if not a["linkedin_note"] and a["linkedin"]]
    if not to_draft_linkedin:
        return

    try:
        linkedin_draft = outreach_message(paper_blurb_text=paper_row["blurb"], channel="LinkedIn", tone_examples=tone_examples)
    except OutreachLLMError as e:
        print(f"  LinkedIn note drafting failed: {e}")
        return

    note = linkedin_draft.strip()[:200]
    for a in to_draft_linkedin:
        notion.set_author_linkedin_note(a["id"], note, status="Message Drafted")
        a["linkedin_note"] = note  # so a later step sees it without a re-fetch
        print(f"  {a['name']}: drafted LinkedIn note ({len(note)} chars)\n    {note}\n")


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
    # out — nothing else (e.g. Selected) is checked. Scheduled Time is an
    # optional additional gate: unset sends now (unchanged default), a
    # future time holds it until a later run. "Skip" is the explicit
    # opt-out option and is left alone entirely — no draft, no send attempt.
    skipped = [a for a in authors if a["send_via"] == "Skip"]
    if skipped:
        print(f"  {len(skipped)} author(s) marked Send Via = Skip — left alone.")

    with_send_via = [a for a in authors if a["send_via"] and a["send_via"] != "Skip"]
    if not with_send_via:
        print("  No authors have a Send Via set in Notion — do that first, then re-run.")
        return

    to_send = [a for a in with_send_via if is_due(a)]
    not_due = len(with_send_via) - len(to_send)
    if not_due:
        print(f"  {not_due} author(s) have a future Scheduled Time — not due yet.")
    if not to_send:
        return

    # Passed uncut — draft_messages decides per-field (Message vs LinkedIn
    # Note) whether an author still needs drafting, since one author can be
    # missing one and not the other.
    draft_messages(notion, paper_row, to_send, tone_examples)

    for author in to_send:
        if author["status"] == "Sent":
            continue  # already sent — never resend on a re-run
        channel = author["send_via"]
        content = author["linkedin_note"] if channel == "LinkedIn" else author["message"]
        if not content:
            continue  # drafting failed above, already reported
        subject = author.get("subject") or "" if channel == "Email" else ""
        sent, note, thread_ref = attempt_send(
            channel, content, author["email"] or "", author["x_handle"],
            x_access_token, gmail_access_token, subject=subject,
        )
        if channel == "LinkedIn":
            notion.set_author_linkedin_note(author["id"], content, status="Message Drafted", post_error=note)
        elif sent:
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
            print("(X not connected — run gtm_agent/x_oauth_login.py to enable real DM sending)\n")

        gmail_access_token = get_gmail_access_token()
        if not gmail_access_token:
            print("(Gmail not connected — run gtm_agent/gmail_oauth_login.py to enable real email sending)\n")

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
