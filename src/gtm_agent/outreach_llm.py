"""OpenAI-backed writing help for research outreach.

The model only ever rephrases facts this app already fetched from OpenAlex or
Semantic Scholar. It is never asked to recall or guess who someone is, where
they work, or where their profiles live — that is exactly the kind of detail an
LLM invents confidently, and a wrong affiliation in a cold email is fatal.
"""

import json
import os

import requests

from gtm_agent.config import ConfigError, get_openai_api_key

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
TIMEOUT_SECONDS = 45

GROUNDING_RULE = (
    "Use only the facts in the JSON provided. Never add employers, titles, locations, "
    "personal details, or claims that are not present. If a fact is missing, leave it out "
    "rather than guessing. A name does not reveal anyone's gender, so never use he or she: "
    "use the person's name or they. Write plainly, with no marketing language and no em dashes."
)


class OutreachLLMError(RuntimeError):
    """Writing help was unavailable. Callers must keep the fetched facts usable."""


def _chat(system: str, user: str, max_tokens: int) -> str:
    try:
        api_key = get_openai_api_key()
    except ConfigError as exc:
        raise OutreachLLMError("OPENAI_API_KEY is not set, so drafting is off. The scholarly facts above still apply.") from exc
    try:
        response = requests.post(
            OPENAI_CHAT_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": DEFAULT_MODEL,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": 0.4,
                "max_tokens": max_tokens,
            },
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    except requests.RequestException as exc:
        raise OutreachLLMError("The writing model is unavailable right now. Please try again shortly.") from exc
    except (KeyError, IndexError, ValueError) as exc:
        raise OutreachLLMError("The writing model returned an unexpected response.") from exc


def author_brief(author: dict, paper: dict | None = None) -> str:
    """Summarize a fetched author profile in two or three sentences."""
    facts = {
        "name": author.get("name"),
        "affiliations": author.get("affiliations"),
        "research_topics": author.get("topics"),
        "papers_published": author.get("paperCount"),
        "total_citations": author.get("citationCount"),
        "h_index": author.get("hIndex"),
        "most_cited_papers": [
            {"title": item.get("title"), "year": item.get("year"), "citations": item.get("citationCount")}
            for item in (author.get("recentPapers") or [])[:5]
        ],
        "paper_you_found_them_through": {"title": (paper or {}).get("title"), "year": (paper or {}).get("year")} if paper else None,
        "affiliation_is_confirmed": author.get("matchedBy") != "name",
    }
    return _chat(
        system=(
            "You brief a researcher before they contact an academic author. "
            "Write two or three sentences covering what this person works on, what their most cited "
            "work is, and how established they are. The paper the user found them through is often "
            "already in their list of papers, so do not describe it as a separate or newer work. "
            "If affiliation_is_confirmed is false, say the affiliation is unconfirmed. " + GROUNDING_RULE
        ),
        user=json.dumps(facts, ensure_ascii=False),
        max_tokens=220,
    )


CHANNEL_GUIDANCE = {
    "Email": "A cold email. Give it a subject line on the first line prefixed 'Subject: ', then the body. Keep the body under 130 words.",
    "LinkedIn": "A LinkedIn connection note. Hard limit of 280 characters total. No subject line, no signature.",
    "X": "A direct message on X. Under 400 characters, conversational, no subject line.",
}


def outreach_draft(*, contact: dict, paper: dict | None, channel: str, purpose: str, sender: str | None = None) -> str:
    """Draft one outreach message from stored contact facts."""
    facts = {
        "recipient_name": contact.get("name"),
        "recipient_affiliation": contact.get("affiliation"),
        "recipient_research_topics": contact.get("topics"),
        "their_paper": {"title": (paper or {}).get("title"), "year": (paper or {}).get("year")} if paper else None,
        "what_you_know_about_them": contact.get("relationship_summary"),
        "your_reason_for_reaching_out": purpose,
        "about_the_sender": sender,
    }
    return _chat(
        system=(
            f"You write outreach to academic researchers on behalf of the sender. {CHANNEL_GUIDANCE.get(channel, CHANNEL_GUIDANCE['Email'])} "
            "Reference their specific work, state the ask once, and close with a low-friction question. "
            "Do not flatter, do not claim to have read work that is not listed, and do not promise anything. "
            "Return the message only, with no commentary. " + GROUNDING_RULE
        ),
        user=json.dumps(facts, ensure_ascii=False),
        max_tokens=400,
    )
