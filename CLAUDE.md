# Working in this repo

## Capture stated opinions into memory, live

`memory/` holds what's been learned about the founder's voice, topics, and
preferences — see `memory/MEMORY.md` and the "Founder memory" section of
`README.md`. It updates two ways, both automatic, no explicit user request
needed for either: every skill that touches Notion or `voice_corpus.json`
runs the procedure in `.claude/memory-update-procedure.md` as its own last
step, every time it runs (it's a fast no-op when there's no new evidence);
and this instruction, for anything the founder says directly.

**Whenever the founder states a preference, opinion, like, or dislike
directly in conversation** — including short, casual, or context-dependent
remarks typed straight into the terminal ("I don't like this", "not a fan
of that one", "meh, skip it", "yeah I like that angle") and not just fully
spelled-out statements ("I don't like when...", "I prefer...") — **append it
immediately** to the relevant memory file's `## Founder notes (manual —
preserved on regeneration)` section, in the same turn, without waiting to be
asked and without waiting for a skill run to pick it up. Don't ask
permission first; just do it and mention it briefly.

- **Resolve the referent before saving.** "I don't like this" on its own is
  useless read back later — write down what "this" concretely was (the
  specific draft text, the reply angle, the topic, the row) plus the
  reaction, not the bare pronoun. If the referent genuinely isn't clear from
  context, ask a quick clarifying question rather than guessing or saving
  something vague.
- One line per note, dated (`YYYY-MM-DD`), in the founder's own terms rather
  than paraphrased into something vaguer.
- Append — never rewrite or remove earlier founder notes, and never edit the
  generated sections above that marker (that's what the automatic per-skill
  update, `.claude/memory-update-procedure.md`, regenerates from real
  activity).
- Pick the file by what the opinion is actually about:
  - `memory/x-voice.md` — how they want X posts/replies to sound
  - `memory/x-topics.md` — what to engage with or avoid on X
  - `memory/outreach-voice.md` / `memory/outreach-topics.md` — same, for
    paper outreach
  - `memory/preferences.md` — anything cross-cutting or that doesn't fit a
    single platform
- If none of the 5 files exist yet, this instruction doesn't apply —
  `memory/` hasn't been set up.
