import re
from pathlib import Path

DEFAULT_INTERESTS_PATH = Path("interests.md")

HEADING_RE = re.compile(r"^\s*#{1,6}\s*(.+?)\s*$")
BULLET_RE = re.compile(r"^\s*[-*]\s+(.+?)\s*$")


def parse_interests(text: str) -> dict:
    """Parse the interests markdown into {"accounts": [...], "topics": [...]}.

    Only `-`/`*` bullets under the Accounts and Topics headings count; prose is
    ignored so the file can carry instructions for whoever edits it."""
    sections: dict[str, list[str]] = {"accounts": [], "topics": []}
    current: str | None = None

    for line in text.splitlines():
        heading = HEADING_RE.match(line)
        if heading:
            name = heading.group(1).strip().lower()
            current = name if name in sections else None
            continue

        bullet = BULLET_RE.match(line)
        if bullet and current:
            value = bullet.group(1).strip()
            if current == "accounts":
                value = value.lstrip("@").strip()
            if value:
                sections[current].append(value)

    return sections


def load_interests(path: Path = DEFAULT_INTERESTS_PATH) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found — it holds the accounts and topics to search."
        )
    return parse_interests(path.read_text())
