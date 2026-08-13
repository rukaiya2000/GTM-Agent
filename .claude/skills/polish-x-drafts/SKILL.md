---
name: polish-x-drafts
description: Rewrite a rough note into a polished X post in the user's own voice, using their already-posted content as style reference. Handles single tweets, multi-tweet threads, and long-form articles. Use when the user pastes a rough note and wants it turned into a post, asks to polish/rewrite a draft from the "Tweet Drafts" Notion database, or asks to retry/rephrase a rejected draft.
---

# Polish X Drafts

Turn a rough note into a polished X post that reads like the author actually wrote it.
Output goes to Notion for human review — never posted from this skill.

## The voice corpus

`voice_corpus.json` (project root) holds the author's previously posted content, split
by format so short-form and long-form voice don't bleed into each other:

```json
{
  "tweets":   [ {"id", "text", "posted_url", "post_type"} ],
  "articles": [ {"id", "title", "text", "posted_url"} ]
}
```

- `tweets` covers both `single-thread` and `multi-thread` posts (short-form voice).
- `articles` is kept separate so long-form voice is referenced only against long-form.
- Every entry is something the author actually wrote and posted.

This file is **read-only for this skill.** It is appended to only at real post time by
`gtm_agent/post_ready.py` / `post_all_due.py`. Never write to it here, even if the user
mentions posting.

**Match reference to the post type being drafted:**
- Drafting a `single-thread` or `multi-thread` → reference `tweets`.
- Drafting an `article` → reference `articles`.

**Don't dump the whole corpus.** Select the ~15–20 most relevant entries as style
exemplars. If the corpus grows large, prefer the closest matches over volume.

**Prefer what actually worked.** Entries may carry a `metrics` object with an
`engagement_rate` (populated by `gtm_agent/fetch_metrics.py`). When present, weight
high-rate posts more heavily — they're evidence of what lands, not just what the
author sounds like. Entries with no `metrics` are unmeasured, **not** bad: never
treat a missing metric as a negative signal, and don't exclude them, especially
when few entries have data at all.

If `voice_corpus.json` is missing or empty, or the relevant bucket has no entries,
ignore it and just polish the rough note directly on its own merits.

Also read `memory/x-voice.md` (repo root) — the same corpus already
distilled into observed tone patterns, with a stated confidence level. Use
it alongside the raw corpus entries below, not instead of them.

## Voice rules

Match the author's voice, don't approximate a generic "good tweet." From the reference
entries, infer and mirror:
- typical length and how much they pack into a post
- capitalization habits (all-lowercase? sentence case? Title Case for emphasis?)
- emoji and hashtag use — how many, where, or none at all
- whether they open with a hook and how
- punctuation quirks, line breaks, list vs prose style
- tone (dry, earnest, punchy, technical)

**Match voice, not wording.** Do not reuse specific phrasings from past posts or clone
a previous post's structure wholesale — a small corpus makes self-plagiarism easy. The
result should feel like a *new* post by the same person.

## Post-type rules (read the `post-type` property)

The row's `post-type` is `single-thread`, `multi-thread`, or `article`. It's a
multi-select, so read the first value. Produce accordingly — the exact `Final Text`
format matters, the posting scripts parse it:

- **single-thread** — one tweet, **≤280 characters.** If the rough note genuinely
  can't fit in 280, don't silently truncate or cram it: flag it and suggest either
  tightening or switching to `multi-thread`.
- **multi-thread** — a sequence of connected tweets, **each ≤280 characters.** Break at
  logical points, not mid-thought. Number them `1/n … n/n` by default (say so in your
  report; the user can drop numbering if they prefer). Store the full thread in
  `Final Text` separated by **a line containing only `---`** between tweets — that's
  the exact separator the posting script splits on.
- **article** — long-form, **not bound by the 280 limit.** Put the body in
  `Final Text` and the headline in the **`Title` property**. If `Title` is already
  filled in, keep it unless it's clearly a placeholder — otherwise write one
  yourself; don't leave it empty. `Post Info` is the row's internal working name,
  *not* the headline — don't copy it into `Title`. Body is plain text; each line
  becomes a paragraph. Rich formatting, embeds, and images aren't supported by
  this pipeline.

For a **pasted note with no row**, there's no `post-type` property to read. Default to
`single-thread` unless the note is clearly long-form or explicitly asks for a thread/
article; state which type you assumed so the user can correct it.

## Drafting a post

1. Get the rough note:
   - pasted directly, or
   - from a `Tweet Drafts` Notion row (data source
     `collection://410eb9c5-f591-82db-8a09-87d289edb063`) with
     `Stage = Ready for AI Review`. The rough note is the row's **page body/content**
     (fetch the page itself, e.g. via `notion-fetch` on its URL) — *not* the
     `Final Text` property, which is empty on unpolished rows and is where the
     finished post gets written, not where it comes from.
   - **If multiple rows are at `Stage = Ready for AI Review`, process all of them,**
     one at a time.
2. Read the `post-type` (or default per the rule above).
3. Read the matching bucket of `voice_corpus.json` for reference (per the corpus rules).
4. Rewrite the rough note into the target post type, following the voice and
   post-type rules.
5. Write it immediately — no chat approval first:
   - From an existing row: set `Final Text` to the result, `Stage = Ready for Human
     Review`, and for articles also set `Title`. Don't touch the page body/content.
   - From a pasted note with no row: create a new page with the rough note as its
     body/content, `post-type` set, `Final Text` = the result, `Title` set for
     articles, `Stage = Ready for Human Review`.
6. Report briefly what was written — including the post type, the title for articles,
   and for threads how many tweets. The user reviews in Notion: `Stage = Rejected
   Agent Post` to reject, edit `Final Text` directly, or `Stage = Ready to post` to
   send it to posting.

## Retrying a rejected draft

For a row with `Stage = Rejected Agent Post`, `Final Text` already holds the rejected
draft — that's the starting point, not the original page body.

1. Fetch the page with `notion-fetch` (`include_discussions: true`) to check for
   comments. If any exist, pull them with `get_comments` and treat them as the reason
   it was rejected — rewrite specifically to address that feedback. If there are no
   comments, produce a distinctly different rephrasing.
2. Keep the same `post-type` unless the feedback asks to change it. Rewrite following the
   same voice, corpus, and post-type rules as drafting (respect the ≤280 per-tweet limit).
3. Write the result to `Final Text`, set `Stage = Ready for Human Review`. For articles,
   revise `Title` too if the feedback was about the headline.
4. Report briefly what changed and why (e.g. what feedback it addressed).

## Update memory (automatic, every run)

After reporting, run the procedure in `.claude/memory-update-procedure.md`
— this skill mainly reads `memory/x-voice.md` rather than generating new
evidence, so it's a silent no-op almost every time; it only writes if this
run's rejection-comment handling revealed something `voice_corpus.json`
doesn't already capture. No user request needed.