"""Export LinkedIn-channel paper authors as CSV lead lists for a LinkedIn
automation tool (currently Linked Helper; the format also suits Waalaxy).

LinkedIn outreach runs through a third-party tool the founder signed up for
— our code never drives LinkedIn itself. These tools have no import API:
they take a CSV of LinkedIn profile URLs uploaded by hand into a campaign.
So this script does the half that can be automated: one CSV per paper (a
campaign maps 1:1 to a paper, since messages are drafted per-paper), plus
the invite note and follow-up drafts printed for pasting into that
campaign's message sequence. Everything after the upload — invite timing,
follow-up chaining, quota pacing, stop-on-reply — is the tool's job.

The CSV carries the name alongside the URL because Linked Helper navigates
profiles more reliably when it knows the full name, not just the URL.

Status stays whatever it was: these tools don't report back to Notion, so
the human flips Status to Sent (campaign launched) / Replied by hand, same
as before. Rows already Sent/Replied are excluded here so a re-export never
re-invites anyone (the tools also dedupe on their side).

    python gtm_agent/export_linkedin_leads.py                 # write exports/linkedin/*.csv
    python gtm_agent/export_linkedin_leads.py --paper ragas   # only papers matching a substring
"""

import argparse
import csv
import re
from pathlib import Path

from gtm_agent.config import ConfigError, get_paper_authors_db_id, get_paper_outreach_db_id
from gtm_agent.notion_client import NotionApiError, NotionClient
from gtm_agent.trajectory import run_main

EXPORT_DIR = Path("exports/linkedin")
# Statuses that mean outreach already went out on some channel — never re-export.
ALREADY_CONTACTED = {"Sent", "Followup 1 Sent", "Followup 2 Sent", "Replied"}
# The founder's own ceiling (stated 2026-08-14), not a tool limit — also
# comfortably inside LinkedIn's ~200/week and safe-daily guidance.
MONTHLY_INVITE_BUDGET = 80


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "paper"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper", default="", help="Only papers whose name contains this substring")
    args = parser.parse_args()

    try:
        paper_db_id = get_paper_outreach_db_id()
        authors_db_id = get_paper_authors_db_id()
        notion = NotionClient()
    except ConfigError as e:
        print(f"Config error: {e}")
        return 1

    try:
        papers = notion.get_paper_outreach_rows(paper_db_id)
        groups = []
        for paper in papers:
            if args.paper and args.paper.lower() not in paper["name"].lower():
                continue
            authors = [
                a
                for a in notion.get_paper_author_rows(authors_db_id, paper_page_id=paper["id"])
                if a["send_via"] == "LinkedIn"
                and a["linkedin"]
                and a["status"] not in ALREADY_CONTACTED
            ]
            if authors:
                groups.append((paper, authors))
    except NotionApiError as e:
        print(f"Notion request failed: {e}")
        return 1

    if not groups:
        print("No LinkedIn authors to export (Send Via = LinkedIn, LinkedIn URL set, not yet contacted).")
        return 0

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    for paper, authors in groups:
        path = EXPORT_DIR / f"{_slug(paper['name'])}.csv"
        with path.open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["linkedin_url", "full_name"])
            for author in authors:
                writer.writerow([author["linkedin"], author["name"]])
        total += len(authors)

        print(f"\n{paper['name']} — {len(authors)} lead(s) -> {path}")
        for author in authors:
            print(f"  {author['name']}: {author['linkedin']}")

        # Campaign sequence content: one invite note per paper (drafts are
        # deliberately generic per-paper, so any author can receive them).
        note = next((a["linkedin_note"] for a in authors if a["linkedin_note"]), "")
        f1 = next((a["followup_1_message"] for a in authors if a["followup_1_message"]), "")
        f2 = next((a["followup_2_message"] for a in authors if a["followup_2_message"]), "")
        if note:
            print(f"  Invite note (paste into the campaign's connection-request step):\n    {note}")
        else:
            print("  No LinkedIn Note drafted yet — run paper-outreach drafting first, or write one in Notion.")
        if f1:
            print(f"  Follow-up 1 (paste as the message step after the accept):\n    {f1}")
        if f2:
            print(f"  Follow-up 2 (paste as the final no-reply step):\n    {f2}")

    print(f"\n{total} lead(s) exported across {len(groups)} paper(s).")
    if total > MONTHLY_INVITE_BUDGET:
        print(
            f"Warning: that's more than the {MONTHLY_INVITE_BUDGET} invites/month "
            "budget — stagger the campaigns."
        )
    print(
        "Next: import each CSV into the LinkedIn tool (one campaign per paper), "
        "paste the note/follow-ups above into that campaign's sequence, then "
        "flip each author's Status to Sent in Notion once the campaign is running."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run_main(main, __file__))
