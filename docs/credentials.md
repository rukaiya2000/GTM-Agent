# Creating the X and Gmail credentials

Step-by-step walkthroughs for the credentials in `.env` that need a developer
console to obtain. Notion and OpenAI keys are covered in the README's
[Configuration](../README.md#configuration) table; this file covers the two
that involve an OAuth app setup. Both are one-time.

All secrets land in `.env`, and both login flows store refreshable tokens in
`x_oauth_token.json` / `gmail_oauth_token.json` — all three files are
gitignored. Never commit any of them.

## X — `X_BEARER_TOKEN`, `X_CLIENT_ID`, `X_CLIENT_SECRET`

The bearer token is app-only and read-only (discovery, mentions, corpus
seeding). The client ID/secret power the OAuth login for everything done *as
your account*: posting, DMs, reading DM replies, private metrics.

1. Sign in at [developer.x.com](https://developer.x.com) **with the X account
   you will post from** and set up a developer account on pay-per-use
   billing, with credits loaded.
2. Under **Projects & Apps**, create (or open) an app inside a project.
3. **Keys and tokens** tab → generate the **Bearer Token** →
   `X_BEARER_TOKEN`.
4. On the app's settings page, find **User authentication settings** → **Set
   up**:
   - **App permissions**: *Read and write and Direct Messages* — write is for
     posting; the DM permission is what later grants the `dm.write` /
     `dm.read` scopes the paper-outreach send and reply-check need.
   - **Type of App**: *Web App, Automated App or Bot* (the confidential
     client type — this is what gives you a client *secret*).
   - **Callback URI / Redirect URL**: `http://127.0.0.1:8765/callback` —
     must match exactly; `gtm_agent/x_oauth_login.py` listens there.
   - **Website URL**: anything valid (your X profile URL works).
5. On save, the portal shows the **OAuth 2.0 Client ID and Client Secret**
   once → `X_CLIENT_ID`, `X_CLIENT_SECRET`. If the secret is lost,
   regenerate it from **Keys and tokens** (this invalidates the old one).
6. Authorize once:

   ```bash
   .venv/bin/python gtm_agent/x_oauth_login.py
   ```

   The browser consent screen opens; on approval the script captures the
   redirect and writes `x_oauth_token.json`. Re-run only if that file is
   deleted or the refresh token is revoked.

## Gmail — `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`

Used by `send_outreach.py` to send outreach email and by
`send_followups.py` to check threads for replies. Scopes requested at login
are `gmail.send` + `gmail.readonly` only.

1. Go to [console.cloud.google.com](https://console.cloud.google.com) signed
   in as the Gmail account that will send outreach, and create a project
   (any name, e.g. `gtm-agent`).
2. **APIs & Services → Library** → search **Gmail API** → **Enable**.
3. Configure the consent screen — the console now calls this **Google Auth
   Platform** (older docs say "OAuth consent screen"). The first-run wizard
   asks for:
   - **App Information**: app name (anything) + your email as user support
     email.
   - **Audience**: **External** — the only option for a plain @gmail.com
     account.
   - **Contact Information**: your email.
   - **Finish**: agree and **Create**.
4. **Audience** page → **Publishing status: Testing** → **Test users** →
   **Add users** → add your own Gmail address. In Testing status only listed
   test users can authorize the app; skipping this fails the login with
   `access_denied`. (If the status is *In production* instead, there is no
   test-user list and none is needed.)
5. **Clients** page → **Create client** → Application type: **Desktop app**
   (required — it permits the loopback redirect on `127.0.0.1:8766` that
   `gtm_agent/gmail_oauth_login.py` uses, with no pre-registered redirect
   URI) → **Create**. Copy the **Client ID** and **Client Secret** →
   `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`. Unlike X, these stay viewable
   later under **Clients**.
6. Authorize once:

   ```bash
   .venv/bin/python gtm_agent/gmail_oauth_login.py
   ```

   Expect a "Google hasn't verified this app" warning — normal for your own
   test app; click **Continue** and approve the two scopes. The script
   writes `gmail_oauth_token.json`.

### Testing-status caveat

While the consent screen is in **Testing**, Google expires refresh tokens
after **7 days**, so `gmail_oauth_login.py` needs re-running weekly. If that
gets annoying, use **Publish app** on the Audience page: an unverified
published app still works for your own account (same warning screen at
login), and refresh tokens then persist indefinitely.
