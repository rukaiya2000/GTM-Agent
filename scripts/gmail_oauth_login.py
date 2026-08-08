import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from gtm_agent.config import ConfigError, get_gmail_client_id, get_gmail_client_secret
from gtm_agent.gmail_oauth import (
    build_authorize_url,
    exchange_code_for_token,
    generate_pkce_pair,
    save_token,
)

REDIRECT_HOST = "127.0.0.1"
REDIRECT_PORT = 8766


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        self.server.oauth_code = query.get("code", [None])[0]
        self.server.oauth_state = query.get("state", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<html><body>Authorized. You can close this window.</body></html>"
        )

    def log_message(self, format, *args):
        pass


def main() -> int:
    try:
        client_id = get_gmail_client_id()
        client_secret = get_gmail_client_secret()
    except ConfigError as e:
        print(f"Config error: {e}")
        return 1

    verifier, challenge = generate_pkce_pair()
    state = secrets.token_urlsafe(16)
    auth_url = build_authorize_url(client_id, challenge, state)

    server = HTTPServer((REDIRECT_HOST, REDIRECT_PORT), _CallbackHandler)
    server.oauth_code = None
    server.oauth_state = None

    print(f"Opening browser for Gmail authorization:\n{auth_url}\n")
    webbrowser.open(auth_url)

    print(f"Waiting for redirect on http://{REDIRECT_HOST}:{REDIRECT_PORT}/callback ...")
    server.handle_request()

    if server.oauth_state != state:
        print("State mismatch — possible CSRF, aborting.")
        return 1
    if not server.oauth_code:
        print("No authorization code received.")
        return 1

    token_response = exchange_code_for_token(server.oauth_code, verifier, client_id, client_secret)
    save_token(token_response)
    print("Saved Gmail OAuth token to gmail_oauth_token.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
