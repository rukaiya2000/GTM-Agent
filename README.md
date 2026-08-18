<p align="center">
  <img src="assets/logo.svg" alt="Wingman" width="440">
</p>

<p align="center">
  <strong>A go-to-market agent for X (and paper outreach) that finds the conversations worth joining and drafts what to say, while you decide what actually goes out.</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/status-work%20in%20progress-F59E0B?style=flat-square" alt="Status: work in progress">
  <img src="https://img.shields.io/badge/python-3.11%2B-3776AB?style=flat-square" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/platform-X-1D9BF0?style=flat-square" alt="Platform: X">
  <img src="https://img.shields.io/badge/storage-Notion-000000?style=flat-square" alt="Storage: Notion">
</p>

---

## What it does

Wingman handles the preparation work around building a presence on X:
finding posts worth replying to, turning rough notes into voice-matched
drafts, and — for a separate paper-outreach workflow — finding paper
authors and drafting outreach messages to them. Everything is staged in
Notion for you to review; nothing gets liked, replied to, sent, or
published without you explicitly approving it first. Drafts are written
in your own voice, conditioned on a corpus of posts you actually
published rather than generic AI output.

Three pipelines, each with its own skills:

- **Engagement** — discover accounts/posts worth engaging with, draft
  replies, and publish the ones you approve.
- **Publishing** — turn a rough note into a polished post/thread/article
  and publish it on schedule (via Typefully for posts/threads/replies,
  direct X API for articles and retweets).
- **Paper outreach** — find a paper's authors, research their contact
  info, and draft/send Email, X DM, or LinkedIn outreach.

## Installation

Requirements: Python 3.11+, a Notion workspace with an internal
integration, an X developer account with pay-per-use credits, Claude Code
or Codex CLI. See `.env.example` for every credential the pipelines can
use (Typefully, Gmail, OpenAI, etc. are only needed for the features that
use them) — [docs/credentials.md](docs/credentials.md) walks through
setting up the X and Gmail OAuth apps click by click.

```bash
uv sync
cp .env.example .env        # fill in credentials, see docs/credentials.md
```

Then, once `.env` is filled in, run once in order:

```bash
.venv/bin/python gtm_agent/smoke_test.py <username>                    # verify auth
.venv/bin/python gtm_agent/setup.py <notion-page-url> <your-username>  # bootstrap Notion + voice corpus
.venv/bin/python gtm_agent/x_oauth_login.py                            # authorize posting
```

The paper-outreach pipeline needs its own Notion databases (Paper
Outreach, Paper Authors) created by hand and their IDs set in `.env` —
ask the `paper-outreach` skill to walk you through it, or see the schema
comments in `gtm_agent/notion_client.py`. Run `gmail_oauth_login.py` too
if you want it to send outreach email.

## Skills

Skills live in `.claude/skills/` and are runnable from Claude Code or
Codex CLI. Scripts do the deterministic, money-spending, or unattended
work; skills add judgement on top (voice matching, curation, drafting).

| Skill | What it does |
|---|---|
| `discover-and-draft-x-replies` | Finds new posts worth replying to and drafts three reply options (plus a retweet message) in your voice. Never posts or changes status — you review and pick in Notion. |
| `publish-x-replies` | Publishes the replies/retweets you've marked ready in the Response Calendar, then reconciles anything scheduled via Typefully. |
| `polish-x-drafts` | Turns a rough note in Notion into a polished single post, thread, or long-form article in your voice. |
| `publish-x-queue` | Publishes the Tweet Drafts you've marked ready, then reconciles anything scheduled via Typefully. |
| `paper-outreach` | Fetches a staged paper's authors, researches missing contact info, and drafts Email/X messages plus a LinkedIn connection-request note. Never sends. |
| `publish-paper-outreach` | Sends the outreach messages you've set `Send Via` on (Email/X), drafts a LinkedIn note for manual copy-paste, and checks for replies/sends follow-ups. |
| `deep-search` | Deep-research a market/company question (e.g. "AI safety companies in SF") by fanning out parallel subagents, and offers to save the results to a `.md` file or Notion. |

## Run trajectories

Every script run records what it did to `runs/` — the prompt that asked for
it, args, the code it ran on, everything it printed, every LLM prompt and
completion with token usage, per-recipient send outcomes, and the traceback
if it died. Read them back with:

```bash
.venv/bin/python gtm_agent/runs.py                     # recent runs
.venv/bin/python gtm_agent/runs.py errors --traceback  # every failure, grouped
.venv/bin/python gtm_agent/runs.py show last           # replay one run
.venv/bin/python gtm_agent/runs.py llm --full          # prompts, drafts, spend
```

Meant for error analysis and for improving the skills' instructions against
real runs rather than memory. `runs/` is gitignored and holds real addresses
and message bodies. See [docs/trajectories.md](docs/trajectories.md).

## Project layout

- `gtm_agent/` — the library and scripts (config, X/Notion/Typefully/Gmail clients, drafting, posting, outreach)
- `.claude/skills/` — the skills listed above
- `memory/` — auto-generated notes on your voice and topic preferences, read by the drafting skills
- `runs/` — one JSONL trajectory per script run, for after-the-fact analysis
- `.env.example` — every credential the project can use, with notes on where to get each one

LinkedIn sending is deliberately never automated — there's no official
API for it, so `paper-outreach` always drafts a note for you to paste in
by hand rather than risking your account with an unofficial one.
