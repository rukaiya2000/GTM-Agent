# Token usage analysis — `draft-x-replies` runs

Point-in-time study, 2026-08-10. Measured from the Claude Code session
transcript (per-message usage across 530 assistant messages, windowed
between the five `/draft-x-replies` invocations of the day) plus the
harness's per-subagent meters. Window caveat: each run's window extends
until the *next* invocation, so trailing conversation bleeds in slightly.

## Per-run parent usage (Claude Fable 5, one long session)

| Run | What it was | Msgs | Output | Cache writes | Cache reads |
|---|---|---:|---:|---:|---:|
| 1 | first curation run (auto-rejected batch) | 41 | 50.9K | 0.19M | 23.6M |
| 2 | Shahul batch, inline drafting | 45 | 84.2K | 1.34M | 26.6M |
| 3 | "nothing new" no-op | 5 | 2.8K | 1.89M | 1.3M |
| 4 | broadened accounts, inline drafts ×10 | 42 | 65.7K | 0.13M | 27.6M |
| 5 | grounded subagent run (+aftermath) | 34 | 206.1K | 4.26M | 19.4M |

Run 5 additionally spent **~365.5K subagent tokens on Sonnet** — 11 agents
(10 rows + 1 accidental duplicate), average **~33K per grounded row**,
range 28.6K–43.1K. The outlier (43K) was the Harvey quip agent burning 24
tool calls fighting X's link blocking; the duplicate wasted ~37K (~10% of
subagent spend).

Whole session for context: 827.8K output, 15.8M cache writes, 239.9M cache
reads across 530 messages.

## Findings

1. **Cache reads dominate, and they are a session-length artifact, not a
   skill cost.** ~25M cache-read tokens per run = ~40 messages × the
   session's ~600K accumulated context (a full day of work in one
   session). At Fable list prices this is ~$25 of a ~$30–80 list-equivalent
   per run — the single biggest line. A fresh session (~50K context) cuts
   it roughly 10×.
2. **The parent is the expensive model doing cheap work.** Run 5's 206K
   Fable output tokens were mostly 11 near-identical subagent prompts plus
   re-writing all 40 drafts after a transport-compression issue mangled
   subagent JSON grammar. The subagents' entire web research (100+
   fetches, all rows) cost less at Sonnet rates (~$2 list) than the
   orchestration did at Fable rates (~$10 list).
3. **Research is cheap and well-bounded.** ~33K tokens per row is stable
   across very different tweets. With the fetch cap at 10 rows, ~350K
   subagent tokens is the practical ceiling per run.

List-price equivalents assume API billing (Fable: $10/M in, $12.5/M cache
write, $1/M cache read, $50/M out; Sonnet: $3/$15). On a Claude
subscription these are notional, not invoiced.

## Optimizations, by impact

1. **Fresh session per run** — removes the dominant cache-read line (~10×).
   Zero code change: invoke the skill in a new Claude Code session.
2. **Write subagent JSON verbatim** — the redo pass doubled parent output;
   retrieve originals instead of re-composing.
3. **Slimmer subagent prompts** — the repeated ~400-word style/rules block
   could live in a shared `style.md` the subagents read (one tool call
   each), saving ~10K parent output per run.
4. **A/B Haiku subagents** — research is mostly reading; ~⅓ the price of
   Sonnet. Check draft quality holds before switching.
5. **Never double-spawn** — one agent per row, keyed by Notion page id
   (the duplicate cost ~10% of subagent spend).

## Bottom line

As executed: **~0.5M parent + ~0.37M subagent tokens per 10-row grounded
run.** Intrinsic cost with a fresh session and verbatim writes: **~0.1M
parent + ~0.35M subagent** — at which point the web research becomes the
main cost, which is where the tokens should be going.

Separate from tokens: `discover.py` X API reads bill as API credits per
fetch, unaffected by any of the above.
