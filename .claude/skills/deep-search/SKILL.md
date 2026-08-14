---
name: deep-search
description: Deep-research a single market/company question (e.g. "ITSM companies in San Francisco", "AI safety companies in San Francisco", "recent YC companies") by fanning out parallel subagents split by source, then merging into one terminal report. Never saves anywhere automatically — offers to save as an .md file or to the Company Research Notion database only after showing results. Use when the user asks to find or research companies in a segment or location.
---

# Deep Search

One query per run. Never combine multiple unrelated topics into a single
run — if asked for several, run them one at a time (or, if asked
explicitly to run several together, still treat each as its own
independent fan-out and report, not one merged subagent set).

**Terminal only by default.** Show the merged report in chat. Only write
an `.md` file or a Notion row if the user asks, and only after the report
is already shown — never save unprompted.

## Step 1 — Scope the query

If the query's time window or sector is genuinely ambiguous (e.g. "recent
YC companies" could mean recent funding, recent launches, or both), ask
one quick clarifying question before spawning anything. Don't ask for
queries that are already unambiguous ("AI safety companies in San
Francisco" needs no clarification).

## Step 2 — Spawn 3 subagents, split by source

Always split the same query by source, not by sub-topic. **Spawn all 3 in
a single message so they run concurrently** — same pattern as
`draft-x-replies`'s research subagents
(`.claude/skills/draft-x-replies/SKILL.md:81-82`).

1. **News/web** — general `WebSearch` for recent articles, launches, press
   coverage of the query.
2. **Funding/startup directories** — `WebSearch` targeted at funding
   announcements and startup-directory phrasing (e.g. `site:crunchbase.com`,
   "raises Series A", "seed round").
3. **Company/professional/code directories** — `WebSearch` targeted at
   `site:linkedin.com/company` for company existence, location, and
   headcount signals, and `site:github.com` for org/product repos —
   useful signal for technical companies (activity, stars, what they've
   actually shipped).

Give each subagent: the exact query, its one source angle, and this exact
instruction to reply with **only** a JSON array, capped at ~8–10 companies:

```json
[{"company": "...", "one_line": "...", "url": "...", "signal_date": "YYYY-MM or null", "source": "news|funding|directory"}]
```

Subagents research and return JSON only — they never write anywhere.

## Step 3 — Merge and report

Collect all 3 subagents' JSON. Normalize company names (case-fold, strip
`Inc.`/`Ltd.`/`Corp.`-style suffixes) to dedupe across sources; where the
same company appears from multiple sources, combine its sources/URLs into
one row. Render one Markdown table in the terminal:

| Company | What they do | Source(s) | Signal date | URL |
|---|---|---|---|---|

Close the report with: the query, the number of unique companies found,
and each subagent's token usage (from its `<usage><subagent_tokens>`
completion tag) plus the total — this is the run's token accounting, no
separate tooling needed.

## Step 4 — Offer to save (only if asked)

After the report, ask: "Want this saved as an `.md` file, pushed to
Notion, or both?" Do nothing further unless the user says yes.

**MD save** — write to `research/deep-search/<slugified-query>-<YYYY-MM-DD>.md`,
containing the query, timestamp, and the same table shown in chat.

**Notion save** — use `gtm_agent/notion_client.py`'s
`create_company_research_row(...)` (direct Notion API via
`NOTION_API_TOKEN`), **not** the `mcp__claude_ai_Notion__*` connector tools
— this repo's Notion connector has previously pointed at the wrong
workspace (see `project_notion_two_workspaces.md`), and every other
pipeline here writes through the direct API for that reason.

- If `NOTION_COMPANY_RESEARCH_DB_ID` is already set in `.env`, write one
  row per unique company directly.
- If it's unset, this is the first save: ask which Notion page to nest the
  new database under (default to the canonical GTM page,
  `c38eb9c5f59183fb9f6981093aea93f9`, if the user doesn't say otherwise —
  never guess a different workspace). Create it with
  `NotionClient.create_database(parent_page_id, title="Company Research",
  schema=COMPANY_RESEARCH_SCHEMA)`, append the returned id as
  `NOTION_COMPANY_RESEARCH_DB_ID=<id>` to `.env`, then write the rows.
  Never create this database without asking first.

## Cost notes

- 3 subagents per run is the default fan-out — don't add a 4th (e.g.
  hiring/job-postings signals) unless asked; keep the run bounded, same
  lesson as `docs/token-usage-analysis.md`'s "never double-spawn."
- Never spawn more than one subagent per source per query.
