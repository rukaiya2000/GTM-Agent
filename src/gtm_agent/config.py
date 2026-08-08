import os

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    pass


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(
            f"{name} is not set. Copy .env.example to .env and fill it in."
        )
    return value


def get_bearer_token() -> str:
    return _require_env("X_BEARER_TOKEN")


def get_x_client_id() -> str:
    return _require_env("X_CLIENT_ID")


def get_x_client_secret() -> str:
    return _require_env("X_CLIENT_SECRET")


def get_gmail_client_id() -> str:
    return _require_env("GMAIL_CLIENT_ID")


def get_gmail_client_secret() -> str:
    return _require_env("GMAIL_CLIENT_SECRET")


def get_notion_token() -> str:
    return _require_env("NOTION_API_TOKEN")


def get_tweet_drafts_db_id() -> str:
    return _require_env("NOTION_TWEET_DRAFTS_DB_ID")


def get_response_calendar_db_id() -> str:
    return _require_env("NOTION_RESPONSE_CALENDAR_DB_ID")


def get_discovery_db_id() -> str:
    return _require_env("NOTION_DISCOVERY_DB_ID")


def get_paper_outreach_db_id() -> str:
    return _require_env("NOTION_PAPER_OUTREACH_DB_ID")


def get_paper_authors_db_id() -> str:
    return _require_env("NOTION_PAPER_AUTHORS_DB_ID")


def get_openai_api_key() -> str:
    return _require_env("OPENAI_API_KEY")


def get_openalex_mailto() -> str | None:
    """Optional. Sending a contact address moves us to OpenAlex's polite pool."""
    return os.environ.get("OPENALEX_MAILTO")


def get_semantic_scholar_api_key() -> str | None:
    """Optional. Without it Semantic Scholar rate-limits most requests."""
    return os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
