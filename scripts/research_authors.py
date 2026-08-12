"""Fan out one web-research subagent per Paper Authors row still missing
contact details, then stage what they find back into Notion for review.

fetch_paper_authors.py (run 1) fills contacts only from the strongest
sources — the arXiv PDF itself and homepages already on file — so most rows
land in "Needs Handles" with just a name and affiliation. This optional
run 1.5 goes further: it spawns one Claude Agent SDK subagent per such
author, each searching the open web (homepages, lab pages, Google Scholar,
X, LinkedIn) and reporting only values a source explicitly states, with the
source cited. Subagents run in parallel on Haiku; the orchestrator only
combines their JSON.

Findings fill the empty contact fields and the row moves to "Needs Review" —
never straight to "Draft Ready", because a web match is a candidate, not a
confirmation. The cited evidence is printed to the console for the human
glance. Rows where nothing was found stay "Needs Handles". Fields a human
already filled in are never overwritten.

    python scripts/research_authors.py                    # research all Needs Handles rows
    python scripts/research_authors.py --dry-run          # research and print, write nothing
    python scripts/research_authors.py --paper attention  # only papers whose name matches

Needs the research extra (pip install -e ".[research]") and a working Claude
Code install. Unlike the rest of this project it spends Anthropic API
tokens — roughly one Haiku subagent per author — and can take a few minutes.
"""

import argparse
import asyncio
import json
import re

from gtm_agent.config import ConfigError, get_paper_authors_db_id, get_paper_outreach_db_id
from gtm_agent.notion_client import NotionApiError, NotionClient

try:
    from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions, ResultMessage, query
except ImportError as e:  # surfaced in main() so --help works without the SDK
    _SDK_IMPORT_ERROR: Exception | None = e
else:
    _SDK_IMPORT_ERROR = None

DEFAULT_LIMIT = 25  # cost guard: authors researched per run

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
X_URL_PATTERN = re.compile(r"(?:https?://)?(?:www\.)?(?:x|twitter)\.com/([A-Za-z0-9_]+)", re.IGNORECASE)

RESEARCHER_PROMPT = """\
You research one research-paper author's public contact details. The task
message gives the author's name, their paper, and anything already known.

Search the web for the author's academic homepage, X (Twitter) handle,
LinkedIn profile URL, professional email address, and current affiliation.
Useful sources: personal or university homepages, lab pages, Google Scholar
profiles, the paper's own landing pages, X posts announcing the paper.

Rules:
- Identity first: confirm a candidate page or account is this author (the
  affiliation, research area, or this specific paper must match) before
  reporting anything from it. Common names collide; when in doubt, report
  nothing.
- Report only values a source explicitly states. Never construct an email
  from an address pattern, and never guess a handle from a name.
- Skip anything marked already known — do not re-verify it.
- confidence is "confirmed" when a source directly ties a value to this
  author (their own homepage, an X account that posted this paper), "likely"
  when only the name and research field match, "none" when nothing was found.

Reply with ONLY this JSON object, no other text:
{"name": "<name exactly as given>", "email": "", "x_handle": "@...", "homepage": "", "linkedin": "", "affiliation": "", "confidence": "confirmed" | "likely" | "none", "evidence": "<one sentence naming the source URL(s)>"}
Use "" for every field no source states.
"""

ORCHESTRATOR_PROMPT = """\
Research public contact details for the paper authors listed below.

Spawn one author-researcher subagent per author — all in a single message so
they run in parallel — passing each subagent its numbered author block
verbatim. Do not research anyone yourself, and do not spawn any other kind
of agent.

<authors>
{blocks}
</authors>

When every subagent has reported, reply with ONLY a JSON array containing
one object per author, in the order listed above. Preserve each subagent's
object as returned, fixing only malformed JSON. No text outside the array.
"""


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z ]", "", name.lower()).strip()


def normalize_x_handle(value: str) -> str:
    """Accepts '@user', 'user', or a profile URL; returns '@user' or ''."""
    value = value.strip()
    if not value:
        return ""
    match = X_URL_PATTERN.search(value)
    if match:
        return f"@{match.group(1)}"
    value = value.lstrip("@")
    return f"@{value}" if re.fullmatch(r"[A-Za-z0-9_]{1,15}", value) else ""


def extract_json_array(text: str) -> list:
    """The orchestrator is told to reply with bare JSON, but tolerate a code
    fence or a sentence of preamble rather than failing the whole run."""
    fenced = re.search(r"```(?:json)?\s*(\[.*?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start = text.find("[")
    if start == -1:
        raise ValueError("no JSON array in agent output")
    parsed, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(parsed, list):
        raise ValueError("agent output is not a JSON array")
    return parsed


def build_author_blocks(tasks: list[dict]) -> str:
    blocks = []
    for i, task in enumerate(tasks, start=1):
        row, paper = task["row"], task["paper"]
        lines = [f"{i}. Name: {row['name']}", f'   Paper: "{paper["name"]}"']
        if paper.get("link"):
            lines.append(f"   Paper link: {paper['link']}")
        if row.get("affiliation"):
            lines.append(f"   Affiliation on record: {row['affiliation']}")
        known = [
            f"{label} {value}"
            for label, value in (
                ("email", row.get("email")),
                ("X handle", row.get("x_handle")),
                ("LinkedIn", row.get("linkedin")),
            )
            if value
        ]
        if known:
            lines.append(f"   Already known (skip): {', '.join(known)}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


async def run_research(prompt: str) -> tuple[str | None, float | None]:
    # The orchestrator gets only the Agent tool plus the subagents' web
    # tools; everything that could touch the filesystem or shell is denied,
    # so the agent can research but is structurally unable to do anything
    # else. Notion writes stay in this script.
    options = ClaudeAgentOptions(
        agents={
            "author-researcher": AgentDefinition(
                description="Web-researches one paper author's public contact details.",
                prompt=RESEARCHER_PROMPT,
                tools=["WebSearch", "WebFetch"],
                model="haiku",
            )
        },
        allowed_tools=["Agent", "WebSearch", "WebFetch"],
        disallowed_tools=["Bash", "Edit", "Write", "NotebookEdit"],
        setting_sources=[],
        max_turns=50,
    )
    result_text = None
    cost = None
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, ResultMessage):
            result_text = message.result
            cost = message.total_cost_usd
    return result_text, cost


def apply_findings(notion: NotionClient, tasks: list[dict], results: list, dry_run: bool) -> None:
    by_name = {_normalize(r.get("name", "")): r for r in results if isinstance(r, dict)}
    for task in tasks:
        row = task["row"]
        found = by_name.get(_normalize(row["name"]))
        if not found:
            print(f"  {row['name']}: no result returned")
            continue

        email = found.get("email", "").strip()
        updates = {
            "email": email if EMAIL_PATTERN.fullmatch(email) else "",
            "x_handle": normalize_x_handle(found.get("x_handle", "")),
            "linkedin": found.get("linkedin", "").strip(),
            "affiliation": found.get("affiliation", "").strip(),
        }
        # Never overwrite what run 1 or a human already put there.
        updates = {k: v for k, v in updates.items() if v and not row.get(k)}

        if not updates:
            print(f"  {row['name']}: nothing found — stays Needs Handles")
            continue

        summary = ", ".join(f"{k}: {v}" for k, v in updates.items())
        evidence = found.get("evidence", "").strip()
        confidence = found.get("confidence", "").strip() or "unstated"
        prefix = "would stage" if dry_run else "staged"
        print(f"  {row['name']}: {prefix} {summary}")
        print(f"    [{confidence}] {evidence or 'no evidence given'}")
        if not dry_run:
            notion.set_author_contact(row["id"], **updates, status="Needs Review")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Research and print, write nothing to Notion")
    parser.add_argument("--paper", default="", help="Only papers whose name contains this substring")
    parser.add_argument(
        "--limit", type=int, default=DEFAULT_LIMIT,
        help=f"Max authors to research per run (default {DEFAULT_LIMIT})",
    )
    args = parser.parse_args()

    if _SDK_IMPORT_ERROR is not None:
        print("claude-agent-sdk is not installed. This optional step needs the research extra:")
        print('  .venv/bin/pip install -e ".[research]"')
        return 1

    try:
        paper_db_id = get_paper_outreach_db_id()
        authors_db_id = get_paper_authors_db_id()
        notion = NotionClient()
    except ConfigError as e:
        print(f"Config error: {e}")
        return 1

    try:
        papers = notion.get_paper_outreach_rows(paper_db_id)
        tasks = []
        for paper in papers:
            if args.paper and args.paper.lower() not in paper["name"].lower():
                continue
            for row in notion.get_paper_author_rows(authors_db_id, paper_page_id=paper["id"]):
                if row["status"] == "Needs Handles":
                    tasks.append({"row": row, "paper": paper})
    except NotionApiError as e:
        print(f"Notion request failed: {e}")
        return 1

    if not tasks:
        print("No authors in Needs Handles — nothing to research.")
        return 0

    if len(tasks) > args.limit:
        print(f"Capping at {args.limit} of {len(tasks)} authors (raise with --limit).")
        tasks = tasks[: args.limit]

    print(f"Researching {len(tasks)} author(s) — one parallel subagent each, this can take a few minutes...")
    prompt = ORCHESTRATOR_PROMPT.format(blocks=build_author_blocks(tasks))
    try:
        result_text, cost = asyncio.run(run_research(prompt))
    except Exception as e:  # CLI missing, auth failure, etc. — SDK exception types vary by version
        print(f"Agent run failed: {e}")
        return 1

    if not result_text:
        print("Agent finished without a result — nothing written.")
        return 1

    try:
        results = extract_json_array(result_text)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"Could not parse agent output ({e}). Raw output:\n{result_text}")
        return 1

    print()
    apply_findings(notion, tasks, results, args.dry_run)
    if cost is not None:
        print(f"\nAgent cost: ${cost:.4f}")
    if not args.dry_run:
        print("Done. Glance over the Needs Review rows in Notion, then set them Draft Ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
