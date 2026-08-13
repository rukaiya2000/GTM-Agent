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


TONE_INSTRUCTION = (
    "previously_sent_messages, if present, are messages the sender has actually sent before — match "
    "their tone, voice, and level of formality. Do not copy their content or claims, only the style."
)


def paper_blurb(paper: dict, notes: str = "", tone_examples: list[str] | None = None) -> str:
    """Short blurb about a paper — the shared context every outreach message
    to its authors builds on."""
    facts = {
        "title": paper.get("title"),
        "year": paper.get("year"),
        "abstract": paper.get("abstract"),
        "topics": paper.get("topics"),
        "your_notes_on_it": notes or None,
        "previously_sent_messages": tone_examples or None,
    }
    return _chat(
        system=(
            "Write a 2-4 sentence blurb about this paper for someone about to reach out to its "
            "authors. Center it on your_notes_on_it if present, since that is the reader's own take "
            "on what mattered — use the abstract only to fill in what the notes don't cover. "
            f"Plain, specific, no marketing language. {TONE_INSTRUCTION} " + GROUNDING_RULE
        ),
        user=json.dumps(facts, ensure_ascii=False),
        max_tokens=220,
    )


CHANNEL_GUIDANCE = {
    "Email": "A cold email. Give it a subject line on the first line prefixed 'Subject: ', then the body. Keep the body under 130 words.",
    "LinkedIn": "A LinkedIn connection note. Hard limit of 280 characters total. No subject line, no signature.",
    "X": "A direct message on X. Under 400 characters, conversational, no subject line.",
}


def outreach_message(
    *, paper_blurb_text: str, channel: str, sender: str | None = None, tone_examples: list[str] | None = None
) -> str:
    """Draft one outreach message for a paper, grounded in the shared blurb.
    Not personalized per recipient — the same message is reused for every
    selected author on a given channel."""
    facts = {
        "paper_blurb": paper_blurb_text,
        "about_the_sender": sender,
        "previously_sent_messages": tone_examples or None,
    }
    return _chat(
        system=(
            f"You write outreach to an academic paper's authors on behalf of the sender. "
            f"{CHANNEL_GUIDANCE.get(channel, CHANNEL_GUIDANCE['Email'])} "
            "Ground the message in paper_blurb. Write it generically enough to send to any of the "
            "paper's authors as-is — do not address a specific person by name. State genuine interest, "
            f"ask one low-friction question, and do not promise anything. Return the message only, with "
            f"no commentary. {TONE_INSTRUCTION} " + GROUNDING_RULE
        ),
        user=json.dumps(facts, ensure_ascii=False),
        max_tokens=400,
    )


FOLLOWUP_CHANNEL_GUIDANCE = {
    "Email": "A short follow-up email replying in the same thread. No subject line, body only. Under 60 words.",
    "X": "A short follow-up direct message on X. Under 200 characters.",
}


def followup_message(
    *, previous_message: str, channel: str, followup_number: int, tone_examples: list[str] | None = None
) -> str:
    """A brief nudge referencing a message that got no reply. Never restates
    the original pitch in full. `followup_number` 2 (the last one, per
    send_followups.py's two-follow-up cap) is written even shorter and gives
    the reader an easy out, since two silences is a stronger signal than one."""
    facts = {
        "previous_message_sent": previous_message,
        "which_followup": f"{followup_number} of 2",
        "previously_sent_messages": tone_examples or None,
    }
    tone_note = (
        "This is the final follow-up — keep it especially brief and give the reader an easy out, "
        "e.g. 'no worries if now isn't a good time'."
        if followup_number >= 2
        else "Keep it brief and low-pressure."
    )
    return _chat(
        system=(
            "You write a brief follow-up to a message that got no reply on behalf of the sender. "
            f"{FOLLOWUP_CHANNEL_GUIDANCE.get(channel, FOLLOWUP_CHANNEL_GUIDANCE['Email'])} "
            f"Reference previous_message_sent briefly rather than restating the full pitch. {tone_note} "
            f"Return the message only, with no commentary. {TONE_INSTRUCTION} " + GROUNDING_RULE
        ),
        user=json.dumps(facts, ensure_ascii=False),
        max_tokens=180,
    )
