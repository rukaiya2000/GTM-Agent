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
| `run_start` | script, argv, the skill it belongs to, git sha + whether the tree was dirty, Python version, pid |
| `stdout` / `stderr` | every line the script printed, teed as it ran |
| `llm` | model, full system and user prompt, the completion, token usage, latency, finish reason — or the error instead |
| `outreach_send` / `outreach_skip` | per-author: channel, recipient, whether it sent, the reason it didn't, the message body |
| `followup_outcome` | per-author: replied, not due (with the day count), sent, send failed, drafting failed |
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

`--script send_outreach` and `--skill publish-paper-outreach` narrow any of
them; `--limit 0` stops truncating to the last 20 runs.

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

Each run is attributed to the skill that drives it. That attribution is
inferred from the script name (see `SCRIPT_SKILL` in
`gtm_agent/trajectory.py`) and recorded as `skill_source: inferred`;
exporting `GTM_SKILL` before a run overrides it and is recorded as `env`.

## Contents

Trajectories hold real recipient addresses, real message bodies and full
prompts — that is the point, since redacted ones can't be analysed. They
stay local: `runs/` is gitignored, and nothing uploads them.
