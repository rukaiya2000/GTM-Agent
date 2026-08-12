# GTM Agent — X / Twitter Component PRD

> Scope: **X only.** Two independent skills. No graph DB, no Hermes/agent runtime — plain code, official X API, Notion as the human surface, small local store for machine bookkeeping. Everything here is single-user (you), run locally.

---

## 0. The two skills at a glance

- **Skill A — Harvest & Rank:** pull recent posts from accounts/topics you track, rank by public engagement, show them to you so *you* engage by hand. Read-only. No automation of likes/replies.
- **Skill B — Draft → Polish → Approve → Schedule → Post:** you dump rough/ungrammatical notes into Notion; the system rewrites them in your voice, writes the polished version back to Notion; you approve by flipping a status; a scheduler posts approved drafts at spaced times.

They share nothing except the X API client and are built/shipped separately.

---

## 1. Stack

| Concern | Choice | Notes |
|---|---|---|
| Data source | **X official API, pay-per-use** | ~$0.005/read, $0.015/text-post, $0.20/link-post, 2M read cap. No free tier. |
| Auth | Bearer token in **env var**, never hardcoded | (The token you pasted earlier is compromised — regenerate it if you haven't.) |
| Post lifecycle + voice corpus | **Notion** (already connected) | Source of truth. Accepted/rejected posts = labeled voice signal. |
| Seen-set + tracked accounts/topics | **Local store** (SQLite file or flat JSON) | Machine bookkeeping, cost-critical, hot path — not Notion. |
| Voice-match retrieval | **Local vector index** over accepted posts | Derived from Notion, not a parallel truth. |
| LLM — bulk (classify/rank) | **Fireworks** (open/cheap) | Only if you need model-based ranking; simple engagement math needs no LLM. |
| LLM — polish (voice) | **Frontier (Anthropic / OpenAI)** | The one step a human reads and judges. |
| Orchestration | **Your code** | On-demand script (Skill A) + cron worker (Skill B). |

---

## 2. Hard constraints (design around these, don't fight them)

1. **Impressions are not available for others' tweets.** The API returns `public_metrics` (likes, reposts, replies, quotes, bookmarks) for any post, but impression/view counts only for **your own** posts (`non_public_metrics`/`organic_metrics`). → Skill A ranks on public engagement, not impressions.
2. **Topic search availability is unverified on pay-per-use.** Reading specific accounts' timelines is fine. "Topics" needs the **recent-search** endpoint (`/2/tweets/search/recent`, ~last 7 days). **Full-archive search is Enterprise-only (~$42k/mo).** You must confirm in the developer portal whether recent-search is callable on your pay-per-use account. If not, "topics" collapses to "topics as seen through tracked accounts."
3. **Every read costs money, per call.** Cost = cadence × accounts × depth. This makes the seen-set and caching non-optional.
4. **Scheduling requires an always-on worker.** The X API does not hold a schedule; *your* system owns the queue and fires posts at their target time. Skill B needs a cron/long-running worker; Skill A does not.
5. **No auto-*selection* of engagement, and no auto-like.** Auto-like/auto-reply is the pattern X suspends accounts for — but that's about a bot deciding what to engage with, not about who clicks "post." Skill A still only surfaces; you still choose the action and text. What *is* automated (as of the Response Calendar posting flow, `publish-x-replies`): firing an already-human-chosen reply or retweet at an already-human-set scheduled time, via `scripts/post_response_calendar.py`. `Like` stays out of scope — no authored text to justify it, and it's the specific action named above.

---

## 3. Data model

### Notion DB — "X Post Pipeline" (source of truth for Skill B)
| Property | Type | Purpose |
|---|---|---|
| Rough note | text | Your raw, ungrammatical input |
| Polished draft | text | System-generated, written back for review |
| Status | select | `draft` → `needs-review` → `approved` → `scheduled` → `posted` / `rejected` |
| Scheduled time | date | When the worker should post it |
| Posted ID | text | X tweet ID after posting (audit) |
| Posted at | date | Timestamp after posting |

- **Accepted (`posted`) rows = positive voice examples. `rejected` rows = negative examples.** This is the training/retrieval corpus for the polish step.

### Tracked list (Skill A config)
- `tracked_accounts` (usernames) and `tracked_topics` (query strings). Put in **Notion** if you want to hand-edit it, or a local config file. Either is fine — it's a short list you edit rarely.

### Local store (machine bookkeeping — not Notion)
- **Seen-set:** `tweet_id`, `fetched_at`. Loaded at start of each Skill A run, checked before every fetch/display, written back at end. SQLite or a JSON set on disk.
- **Vector index:** embeddings of accepted posts (pulled from Notion), for voice-match retrieval in Skill B.

---

## 4. Skill A — Harvest & Rank

**Flow:**
1. Load `tracked_accounts` / `tracked_topics` and the seen-set.
2. For each account: resolve username → user ID (`GET /2/users/by/username/:username`), then fetch recent posts (`GET /2/users/:id/tweets`) with `tweet.fields=public_metrics,created_at`.
3. For topics (if recent-search is available): `GET /2/tweets/search/recent?query=...` with the same fields.
4. **Dedupe against seen-set** — drop anything already fetched. Add new IDs to the set.
5. Rank by an engagement proxy (e.g. weighted likes + reposts + replies + bookmarks; optionally recency-decayed).
6. Present the ranked list to you (Notion page, local HTML, or terminal — your pick) with links to each post.
7. **You engage manually.** No API writes here.

**Cost dial (decide cadence deliberately):**
- 30 accounts × 20 posts = 600 reads ≈ **$3/run.**
- Daily ≈ **~$90/mo.** On-demand (when you sit down to engage) ≈ **pennies.**
- Seen-set + caching means re-runs only pay for *new* posts, not the whole set again.

**Ship criterion:** one session where you engage with ≥3 relevant posts surfaced by it that you'd otherwise have missed, and a re-run doesn't re-charge you for already-seen tweets.

---

## 5. Skill B — Draft → Polish → Approve → Schedule → Post

**Flow:**
1. **Poll Notion** for `draft` rows (cron worker, e.g. every N minutes).
2. **Polish:** frontier model rewrites the rough note into a post, **conditioned on retrieved accepted posts** (voice match) — retrieval pulls your closest past *approved* posts from the vector index and feeds them as style exemplars. Write result to `Polished draft`, set status → `needs-review`.
3. **You review in Notion.** Edit if needed; flip status to `approved` (+ set `Scheduled time`), or `rejected`.
4. **Scheduler** (same worker) polls for `approved` rows with a due/near `Scheduled time`, **spaces them** (don't fire a batch at once), posts via `POST /2/tweets`, then writes back `Posted ID` + `Posted at`, status → `posted`.
5. Rejected/posted rows feed back into the voice corpus.

**Cost:** text post $0.015; **link post $0.20 (13×).** If your posts routinely carry links, that's the dominant cost — worth knowing before you set volume.

**Ship criterion:** a rough note you typed becomes a posted tweet in your voice, gated by a single Notion status flip, posted at the time you set — with zero hand-editing of the polished draft on a good day.

---

## 6. Provider routing (this component)

- **Polish step → frontier (Anthropic/OpenAI).** It's your voice, read by humans. Don't cheap out.
- **Everything else → cheap or no LLM.** Ranking is arithmetic on `public_metrics`; it needs no model. Only reach for Fireworks if you later want model-based relevance filtering on topics.

---

## 7. Build order

1. **X API client + auth** (env var token) + a one-call smoke test (`users/by/username`) once credits are loaded.
2. **Skill A** — accounts-only first (timelines), seen-set, ranking, display. Add topics/recent-search *after* verifying it's callable.
3. **Notion pipeline DB** + read/write from code.
4. **Skill B polish** (frontier + voice retrieval), write-back to Notion, manual approve.
5. **Scheduler worker** — the always-on piece. Add last; it's the only long-running component.

---

## 8. Open items to close before building

1. **Load X credits.** Nothing calls until the pay-per-use balance is non-zero (your `402 credits depleted` was exactly this, not an auth failure).
2. **Verify recent-search availability** on your pay-per-use account in the developer portal. Determines whether "topics" is real or collapses to tracked-accounts-only.
3. **Skill A cadence** — daily vs on-demand. Sets the monthly cost (~$90 vs pennies) and whether Skill A wants its own scheduled run.
4. **Do your posts routinely contain links?** Sets Skill B's real posting cost (13× for links).
5. **Regenerate the Bearer token** you pasted earlier; keep the new one in an env var only.

---

## Explicitly out of scope (deferred / cut)

- Graph DB / context graph — not needed for these two skills; belongs to the relationship side you've deferred.
- Hermes / agent runtime — the only LLM step here is "polish," a single call, not an agent chain.
- Auto-*like*, and any auto-*selection* of what to engage with (the model
  choosing on its own). Posting an already-human-chosen reply/retweet at an
  already-human-set scheduled time is now in scope — see hard constraint #5.
- Unanswered-message handling — deferred by your call.
- Impression-based ranking — data isn't available for others' posts.
