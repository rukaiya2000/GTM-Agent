"""Pull papers staged in the Paper-outreach Notion database, resolve their
authors via OpenAlex/Semantic Scholar, and stage rows in Paper Authors.

By default the top 5 authors are fetched — corresponding authors first (if
OpenAlex flagged any), then the rest in listed order, since author order
itself is a signal of contribution. Pass extra names to also fetch specific
co-authors beyond that on request.

    python gtm_agent/fetch_paper_authors.py                  # process all New papers
    python gtm_agent/fetch_paper_authors.py --all-authors     # fetch every author, not just the top 5

Handles (X/LinkedIn/email) are filled in only when a source actually states
them. Email comes from the corresponding-author footnote printed in the
arXiv PDF itself, when there is one — the strongest signal available, and
also what decides who counts as "Corresponding" over the first-author
fallback. OpenAlex/S2 rarely carry socials, so most rows will come back with
just name + affiliation and a "Needs Handles" status for you to fill in by
hand in Notion — or to let gtm_agent/research_authors.py (run 1.5) take a
web-research pass at first.

Also generates the paper's Blurb (from the abstract + your Notes, drawing on
your own already-sent messages as a tone example). This is run 1 of the
workflow: this populates everything automatically; run 2
(research_authors.py, optional) fills in remaining handles; run 3
(send_outreach.py --draft-only) drafts a Subject + Message for every author
with a contact on file, no manual setup needed first. Sending is a separate,
explicit step (send_outreach.py without the flag).
"""

import argparse
import re

from gtm_agent import handle_search, paper_pdf, scholar
from gtm_agent.config import ConfigError, get_paper_authors_db_id, get_paper_outreach_db_id
from gtm_agent.notion_client import NotionApiError, NotionClient
from gtm_agent.outreach_llm import OutreachLLMError, paper_blurb
from gtm_agent.x_client import XClient

SOCIAL_PATTERN = re.compile(r"(?:https?://)?(?:www\.)?(x|twitter)\.com/([A-Za-z0-9_]+)", re.IGNORECASE)


def extract_x_handle(url: str | None) -> str | None:
    if not url:
        return None
    match = SOCIAL_PATTERN.search(url)
    return f"@{match.group(2)}" if match else None


DEFAULT_AUTHOR_LIMIT = 5


def pick_top(authors: list[dict], priority_names: set[str], limit: int = DEFAULT_AUTHOR_LIMIT) -> list[dict]:
    """`priority_names` (PDF-confirmed correspondence + OpenAlex-flagged
    corresponding authors) go first, then the rest in listed order, capped at
    `limit`. If nothing flags a lead at all, the first-listed author is used
    as the closest free proxy, since arXiv preprints usually carry no
    corresponding-author metadata."""
    if not priority_names:
        priority_names = {authors[0]["name"]}
    priority = [a for a in authors if a["name"] in priority_names]
    rest = [a for a in authors if a["name"] not in priority_names]
    return (priority + rest)[:limit]


def enrich(author: dict, paper_title: str = "", arxiv_id: str | None = None, x_client: XClient | None = None) -> dict:
    """Fill socials from the most confident source available, in order:
    homepage on file (confirmed), then X search (candidate, needs a glance).
    Leaves fields blank rather than guessing when nothing supports a value."""
    homepage = None
    author_id = author.get("authorId")
    if author_id:
        try:
            homepage = scholar.get_author(author_id).get("homepage")
        except scholar.ScholarError:
            pass

    x_handle = extract_x_handle(homepage) or ""
    if x_handle:
        return {"x_handle": x_handle, "linkedin": "", "confidence": "homepage"}

    if x_client is not None:
        match = handle_search.find_x_handle(x_client, author["name"], paper_title, arxiv_id)
        if match:
            return {"x_handle": match["handle"], "linkedin": "", "confidence": match["confidence"]}

    return {"x_handle": "", "linkedin": "", "confidence": ""}


def process_paper(
    notion: NotionClient,
    authors_db_id: str,
    paper_row: dict,
    fetch_all: bool,
    x_client: XClient | None,
    tone_examples: list[str],
) -> None:
    query = paper_row["link"] or paper_row["name"]
    try:
        results = scholar.search_papers(query)
    except scholar.ScholarError as e:
        print(f"  Could not resolve paper: {e}")
        return
    if not results:
        print("  No match found on OpenAlex/Semantic Scholar.")
        notion.set_paper_status(paper_row["id"], "Needs Review")
        return

    paper = results[0]
    authors = paper.get("authors") or []
    if not authors:
        print("  Paper resolved but no author list available.")
        notion.set_paper_status(paper_row["id"], "Needs Review")
        return

    if not paper_row["name"]:
        # A row staged with only a link has no title, which also leaves the
        # `Paper` relation column blank on every linked Paper Authors row.
        notion.set_paper_name(paper_row["id"], paper["title"])
        paper_row["name"] = paper["title"]

    arxiv_id = (paper.get("externalIds") or {}).get("ArXiv")
    if not arxiv_id and paper_row.get("link"):
        # OpenAlex's own arxiv field is often null even when the work was
        # matched via an arXiv link/id (e.g. it only has a DOI on file from a
        # proceedings version) — fall back to what the link itself says.
        match = scholar.ARXIV_PATTERN.search(paper_row["link"])
        arxiv_id = match.group(1) if match else None
    pdf_emails: dict[str, str] = {}
    if arxiv_id:
        pdf_emails = paper_pdf.find_author_emails(arxiv_id, [a["name"] for a in authors])

    corresponding_flagged = {a["name"] for a in authors if a.get("isCorresponding")}
    lead_names = set(pdf_emails) | corresponding_flagged  # PDF footnote is the strongest signal available

    top = pick_top(authors, lead_names)
    top_names = {a["name"] for a in top}

    print(f"  Resolved: {paper['title']} ({paper.get('year')})")
    for a in authors:
        tags = []
        if a["name"] in pdf_emails:
            tags.append(f"email: {pdf_emails[a['name']]}")
        if a["name"] in top_names:
            tags.append("FETCH")
        suffix = f" [{', '.join(tags)}]" if tags else ""
        print(f"    - {a['name']}{suffix} — {a.get('affiliation') or 'no affiliation on record'}")

    to_fetch = list(top)
    if fetch_all:
        to_fetch = authors
    else:
        try:
            extra = input("  Also fetch anyone by name (comma-separated, or Enter to skip): ").strip()
        except EOFError:
            # stdin closed (script run unattended without `yes ""` piped in)
            # — treat as Enter rather than crashing the rest of the batch.
            extra = ""
        if extra:
            wanted = {n.strip().lower() for n in extra.split(",") if n.strip()}
            to_fetch += [a for a in authors if a["name"].lower() in wanted and a["name"] not in top_names]

    for author in to_fetch:
        socials = enrich(author, paper_title=paper["title"], arxiv_id=arxiv_id, x_client=x_client)
        email = pdf_emails.get(author["name"], "")
        role = "Corresponding" if author["name"] in lead_names else "Co-author"
        # "homepage"/"high" are corroborated, same as an email printed in the
        # paper itself; "low" is a bare-name search match — kept in the field
        # for convenience but still needs a human glance before it's "ready".
        confirmed = bool(email) or socials["confidence"] in ("homepage", "high")
        status = "Draft Ready" if confirmed else "Needs Handles"
        notion.create_paper_author_row(
            authors_db_id,
            paper_row["id"],
            name=author["name"],
            affiliation=author.get("affiliation") or "",
            role=role,
            email=email,
            x_handle=socials["x_handle"],
            linkedin=socials["linkedin"],
            status=status,
        )
        note = f" [unconfirmed match, verify: {socials['x_handle']}]" if socials["confidence"] == "low" else ""
        print(f"    staged: {author['name']} ({role}, {status}){note}")

    if paper_row["blurb"]:
        notion.set_paper_status(paper_row["id"], "Blurb Ready")
        return

    try:
        blurb = paper_blurb(paper, paper_row["notes"], tone_examples=tone_examples)
    except OutreachLLMError as e:
        print(f"  Blurb generation failed: {e}")
        notion.set_paper_status(paper_row["id"], "Needs Review")
        return

    notion.set_paper_blurb(paper_row["id"], blurb)
    notion.set_paper_status(paper_row["id"], "Blurb Ready")
    print(f"  Blurb: {blurb}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all-authors", action="store_true",
        help="Fetch every author instead of just the top 5",
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
        papers = notion.get_paper_outreach_rows(paper_db_id, status="__empty__")
        papers += notion.get_paper_outreach_rows(paper_db_id, status="New")
    except NotionApiError as e:
        print(f"Notion request failed: {e}")
        return 1

    if not papers:
        print("No new papers to process.")
        return 0

    try:
        x_client = XClient()
    except ConfigError:
        x_client = None
        print("(X_BEARER_TOKEN not set — skipping X search, using homepage data only)\n")

    tone_examples = notion.get_sent_messages(authors_db_id)

    for paper_row in papers:
        print(f"\n{paper_row['name']}")
        process_paper(notion, authors_db_id, paper_row, args.all_authors, x_client, tone_examples)

    print("\nDone. Next: research_authors.py for any Needs Handles rows, then send_outreach.py --draft-only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
