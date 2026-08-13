# Voice, style, and hard rules for reply drafting

Single source of truth for every drafter — the parent session (inline rows)
and every research subagent must read this file before writing anything.

## Voice

Read the `tweets` bucket of `voice_corpus.json` (repo root). Entries with
`post_type: "reply"` or `"quote"` are things the author actually sent —
weight those highest. Prefer entries with higher `metrics.engagement_rate`,
but treat a missing metric as unmeasured, never as bad. Match the author's
tone, vocabulary, technical depth, and punctuation habits. If the corpus is
missing or nearly empty, write plainly rather than inventing a voice, and
say so.

Also read `memory/x-voice.md` (repo root) — the same corpus and any posted
replies, already synthesized into observed patterns, with an explicit
confidence level. It supplements this file; where the two disagree, the
binding rules below win.

A reply is responsive and conversational: it assumes the original post as
context and doesn't re-introduce what the reader can already see. A retweet
message is closer to a broadcast: it frames the post for the author's
followers in one or two sentences.

## Standing style direction (binding — beats any corpus habit)

- technical and peer-level, in a founder/executive voice
- concise: **max 220 characters and 1–2 sentences each** (deliberately
  tighter than X's 280 limit)
- curious or additive — the goal is to engage researchers/builders and
  start a thoughtful conversation
- not salesy; don't mention the company unless directly relevant
- no emojis, no bulleting, no hashtags
- no jargon overload unless the tweet itself is highly technical
- sound natural on X, not like a memo

## What to write per row

`reply_1/2/3` — **three different angles**, not three rewordings: a
concrete detail or counter-example from the sources read; directly relevant
first-hand experience; a specific genuine question; a respectful
complication of a claim; a connection to adjacent work.

`retweet_message` — one suggested quote line framing the post, same style.

## Hard rules

- **No empty agreement or generic praise.** If a reply carries no
  information, it's not worth sending.
- No flattery, no thread-hijacking into self-promotion, no restating the
  post.
- Don't invent facts, papers, numbers, or experiences the author hasn't
  had. Cite only what you actually read — never what a link "probably"
  says.
- If the post genuinely doesn't warrant a reply, fill the fields anyway and
  note it — the rejection call is the author's.
