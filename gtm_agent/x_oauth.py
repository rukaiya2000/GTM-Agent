import base64
import hashlib
import json
import secrets
import time
import urllib.parse
from pathlib import Path

import requests

from gtm_agent.config import ConfigError

AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
REDIRECT_URI = "http://127.0.0.1:8765/callback"
# dm.read: checking a DM conversation for a reply before sending a follow-up
# (gtm_agent/send_followups.py).
SCOPES = "tweet.read tweet.write dm.write dm.read users.read offline.access"
TOKEN_PATH = Path("x_oauth_token.json")

# Refresh this many seconds before actual expiry, to avoid using a token
# that expires mid-request.
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
    }
    return f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"


def exchange_code_for_token(
    code: str, code_verifier: str, client_id: str, client_secret: str
) -> dict:
    response = requests.post(
        TOKEN_URL,
        auth=(client_id, client_secret),
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": code_verifier,
        },
    )
    response.raise_for_status()
    return response.json()


def refresh_access_token(refresh_token: str, client_id: str, client_secret: str) -> dict:
    response = requests.post(
        TOKEN_URL,
        auth=(client_id, client_secret),
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )
    response.raise_for_status()
    return response.json()


def save_token(token_response: dict, path: Path = TOKEN_PATH) -> None:
    data = {
        "access_token": token_response["access_token"],
        "refresh_token": token_response.get("refresh_token"),
        "expires_at": time.time() + token_response.get("expires_in", 0),
    }
    with open(path, "w") as f:
        json.dump(data, f)


def load_token(path: Path = TOKEN_PATH) -> dict | None:
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def get_valid_access_token(
    client_id: str, client_secret: str, path: Path = TOKEN_PATH
) -> str:
    token = load_token(path)
    if not token:
        raise ConfigError(
            "No X OAuth token found. Run gtm_agent/x_oauth_login.py first."
        )

    if time.time() < token["expires_at"] - EXPIRY_BUFFER_SECONDS:
        return token["access_token"]

    if not token.get("refresh_token"):
        raise ConfigError(
            "X OAuth token expired and no refresh_token is available. "
            "Run gtm_agent/x_oauth_login.py again."
        )

    refreshed = refresh_access_token(token["refresh_token"], client_id, client_secret)
    save_token(refreshed, path)
    return refreshed["access_token"]
