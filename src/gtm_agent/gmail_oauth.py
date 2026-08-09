import base64
import hashlib
import json
import secrets
import time
import urllib.parse
from pathlib import Path

import requests

from gtm_agent.config import ConfigError

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REDIRECT_URI = "http://127.0.0.1:8766/callback"
# send: outreach email. readonly: checking a thread for a reply before
# sending a follow-up (scripts/send_followups.py) — never used to read
# unrelated mail, only threads this app itself started.
SCOPES = "https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly"
TOKEN_PATH = Path("gmail_oauth_token.json")

EXPIRY_BUFFER_SECONDS = 120


def generate_pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def build_authorize_url(client_id: str, code_challenge: str, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        # access_type=offline gets a refresh_token; prompt=consent forces Google to
        # issue one even on a re-auth, which it otherwise skips after the first grant.
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def exchange_code_for_token(code: str, code_verifier: str, client_id: str, client_secret: str) -> dict:
    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": code_verifier,
        },
    )
    response.raise_for_status()
    return response.json()


def refresh_access_token(refresh_token: str, client_id: str, client_secret: str) -> dict:
    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    response.raise_for_status()
    return response.json()


def save_token(token_response: dict, path: Path = TOKEN_PATH) -> None:
    existing = load_token(path) or {}
    data = {
        "access_token": token_response["access_token"],
        # Google only returns refresh_token on the very first consent grant —
        # keep the old one on refresh responses that don't include a new one.
        "refresh_token": token_response.get("refresh_token") or existing.get("refresh_token"),
        "expires_at": time.time() + token_response.get("expires_in", 0),
    }
    with open(path, "w") as f:
        json.dump(data, f)


def load_token(path: Path = TOKEN_PATH) -> dict | None:
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def get_valid_access_token(client_id: str, client_secret: str, path: Path = TOKEN_PATH) -> str:
    token = load_token(path)
    if not token:
        raise ConfigError("No Gmail OAuth token found. Run scripts/gmail_oauth_login.py first.")

    if time.time() < token["expires_at"] - EXPIRY_BUFFER_SECONDS:
        return token["access_token"]

    if not token.get("refresh_token"):
        raise ConfigError("Gmail OAuth token expired and no refresh_token is available. Run scripts/gmail_oauth_login.py again.")

    refreshed = refresh_access_token(token["refresh_token"], client_id, client_secret)
    save_token(refreshed, path)
    return refreshed["access_token"]
