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

Then attempts to actually send. Right now no channel is wired up to a real
send API yet (see attempt_send below) — Email needs Gmail credentials,
X needs a dm.write-scoped OAuth token, and LinkedIn has no send API at all,
ever. Until those exist, everything drafts and prints for you to copy-paste,
and Status stays "Message Drafted" rather than "Sent".

    python scripts/send_outreach.py
"""

from gtm_agent.config import ConfigError, get_paper_authors_db_id, get_paper_outreach_db_id
from gtm_agent.notion_client import NotionApiError, NotionClient
from gtm_agent.outreach_llm import OutreachLLMError, outreach_message

READY_STATUSES = ("Needs Review", "Blurb Ready")


def attempt_send(channel: str, message: str) -> tuple[bool, str]:
    """Returns (sent, note). Nothing actually sends yet for any channel:
    Email needs Gmail credentials + a send function, X needs a
    dm.write-scoped OAuth token + a send function, LinkedIn has no
    third-party send API at all. Swap in a real call here per channel once
    those exist — the rest of the pipeline already expects this shape."""
    if channel == "Email":
        return False, "Gmail isn't connected yet — copy the message above and send it yourself."
    if channel == "X":
        return False, "X DM sending isn't connected yet — copy the message above and send it yourself."
    if channel == "LinkedIn":
        return False, "LinkedIn has no send API — copy the message above and send it yourself."
    return False, f"Unknown channel {channel!r}."


def send_for_paper(notion: NotionClient, authors_db_id: str, paper_row: dict, tone_examples: list[str]) -> None:
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
        if not author["message"]:
            continue  # drafting failed above, already reported
        sent, note = attempt_send(author["send_via"], author["message"])
        status = "Sent" if sent else "Message Drafted"
        notion.set_author_message(author["id"], author["message"], status=status)
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

    for paper_row in papers:
        print(f"\n{paper_row['name']}")
        send_for_paper(notion, authors_db_id, paper_row, tone_examples)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
