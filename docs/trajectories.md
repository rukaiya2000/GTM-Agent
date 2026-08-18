# Run trajectories

Every script run writes an append-only JSONL trajectory under `runs/`, so a
run can be examined after the fact instead of being reconstructed from
whatever scrolled past in the terminal. `gtm_agent/runs.py` reads them back.

Nothing needs to be turned on. `GTM_TRAJECTORY=0` turns it off for a run,
and `GTM_RUNS_DIR` moves where the files land.

## What a run records

```
runs/
  index.jsonl              one summary line per run — script, skill, status, duration
  2026-08-18/
    20260818-185733-send_followups-9a1c.jsonl
```

Inside a run file, one JSON object per line, in the order things happened:

| `kind` | What it holds |
|---|---|
| `run_start` | script, argv, **the prompt that asked for it**, the skill it belongs to, git sha + whether the tree was dirty, Python version, pid |
| `stdout` / `stderr` | every line the script printed, teed as it ran |
| `llm` | model, full system and user prompt, the completion, **reasoning if the model emits any**, token usage, latency, finish reason — or the error instead |
| `outreach_send` / `outreach_skip` | per-author: channel, recipient, whether it sent, the reason it didn't, the message body |
| `followup_outcome` | per-author: replied, not due (with the day count), sent, send failed, drafting failed |
| `followup_scheduled` | per-author: both follow-up due dates and which drafts were written at send time |
| `paper_staged` | how many authors were staged, skipped, held by `Scheduled Time`, and due |
| `step_start` / `step_end` | a named phase and how long it took, recorded even when it raises |
| `error` | exception type, message, full traceback |
| `run_end` | `ok` / `failed` / `crashed` / `interrupted`, exit code, duration, event counts |

Failure behaviour is unchanged by the recording: the traceback still prints
and the exit code still comes from Python. The trajectory is written
alongside, flushed line by line so a crashed run still leaves one behind.

## Reading them back

```bash
.venv/bin/python gtm_agent/runs.py                        # recent runs, newest last
.venv/bin/python gtm_agent/runs.py --failed               # only the ones that didn't end ok
.venv/bin/python gtm_agent/runs.py errors --traceback     # every failure, grouped by script and type
.venv/bin/python gtm_agent/runs.py show last              # replay one run in order
.venv/bin/python gtm_agent/runs.py show last --prompts    # ...including the full LLM prompts
.venv/bin/python gtm_agent/runs.py llm --full             # every prompt/draft pair, with token totals
.venv/bin/python gtm_agent/runs.py summary                # per-script health, per-item outcomes, spend
```

`--script send_outreach`, `--skill publish-paper-outreach` and `--asked
"follow-up"` narrow any of them; `--limit 0` stops truncating to the last 20
runs.

`show` is the one to pipe into a model when a run went wrong in a way that
needs judgement rather than a grep — it prints the whole trajectory,
prompts and message bodies included.

## Using them to improve a skill

The two questions worth asking of a stack of runs:

- **What keeps breaking, and is it the skill's fault?** `runs.py errors`
  separates config and auth failures (expired Gmail token, missing key) from
  genuine logic failures. The first kind belongs in the skill's instructions
  as a check; the second is a bug.
- **Are the drafts any good, and which prompt produced them?** `runs.py llm
  --full` pairs every prompt with what came back and what it cost. That pair
  is the unit of evaluation — a draft judged without its prompt tells you
  nothing about what to change.

## Where the prompt comes from

A run records what the human asked for, so a trajectory can be read without
remembering the conversation around it. It is lifted from the live Claude
Code session transcript — found by `CLAUDE_CODE_SESSION_ID`, read from the
tail so a multi-megabyte transcript costs nothing — and is the most recent
typed prompt at the moment the script started. `GTM_PROMPT` overrides it,
and outside Claude Code there is simply no prompt on the record.

Claude's own reasoning is *not* captured, because it isn't there to capture:
the harness writes thinking blocks to the transcript with their text
stripped. The `reasoning` field on an `llm` event is the drafting model's
own chain, which arrives only from reasoning models — `gpt-4o-mini` sends
none, so the field stays empty until `OPENAI_MODEL` changes.

Each run is attributed to the skill that drives it. Where the transcript
names one, that is used (`skill_source: transcript`); otherwise it is
inferred from the script name (see `SCRIPT_SKILL` in
`gtm_agent/trajectory.py`) and recorded as `inferred`. `GTM_SKILL` beats
both and is recorded as `env`.

## Contents

Trajectories hold real recipient addresses, real message bodies, full
prompts and whatever you typed to ask for the run — that is the point, since redacted ones can't be analysed. They
stay local: `runs/` is gitignored, and nothing uploads them.
