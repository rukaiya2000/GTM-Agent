"""Read back the run trajectories written by gtm_agent/trajectory.py.

The trajectories exist to answer three questions after the fact: what broke
and how often, what the model was actually asked and what it wrote back, and
what a single run did step by step. One subcommand each.

    python gtm_agent/runs.py                       # recent runs, newest last
    python gtm_agent/runs.py errors                # every failure, grouped
    python gtm_agent/runs.py show <run-id|last>    # replay one run
    python gtm_agent/runs.py llm                   # prompts, drafts, tokens
    python gtm_agent/runs.py summary               # per-script health + spend

`show` prints whole prompts and message bodies, so it is the one to pipe into
a model when a run went wrong in a way that needs judgement rather than a
grep.
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from gtm_agent import trajectory

STATUS_MARK = {"ok": "ok", "failed": "FAILED", "crashed": "CRASHED", "interrupted": "interrupted"}


def load_index() -> list[dict]:
    path = trajectory.RUNS_DIR / trajectory.INDEX_NAME
    if not path.exists():
        return []
    runs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                runs.append(json.loads(line))
            except ValueError:
                continue  # a half-written line from a killed process
    return runs


def load_events(run: dict) -> list[dict]:
    path = Path(run["path"])
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
    return events


def resolve(runs: list[dict], ref: str) -> dict | None:
    """Accepts a full run id, a unique prefix, a script name (its latest run),
    or `last`."""
    if not runs:
        return None
    if ref in {"last", "latest"}:
        return runs[-1]
    exact = [r for r in runs if r["run_id"] == ref]
    if exact:
        return exact[-1]
    prefixed = [r for r in runs if r["run_id"].startswith(ref)]
    if prefixed:
        return prefixed[-1]
    by_script = [r for r in runs if r["script"] == ref]
    return by_script[-1] if by_script else None


def select(runs: list[dict], args) -> list[dict]:
    if args.script:
        runs = [r for r in runs if r["script"] == args.script]
    if args.skill:
        runs = [r for r in runs if r.get("skill") == args.skill]
    if getattr(args, "failed", False):
        runs = [r for r in runs if r["status"] != "ok"]
    return runs[-args.limit:] if args.limit else runs


def cmd_list(runs: list[dict], args) -> int:
    chosen = select(runs, args)
    if not chosen:
        print("No runs recorded yet.")
        return 0
    for run in chosen:
        errors = run["counts"].get("error", 0)
        extra = f"  {errors} error(s)" if errors else ""
        print(
            f"{run['started_at']}  {run['run_id']:<44} {STATUS_MARK.get(run['status'], run['status']):<11}"
            f" {run['duration_s']:>7.1f}s  {run.get('skill') or '-':<26}{extra}"
        )
    print(f"\n{len(chosen)} run(s). `runs.py show <run-id>` to replay one.")
    return 0


def cmd_errors(runs: list[dict], args) -> int:
    grouped: dict[tuple[str, str], list[tuple[dict, dict]]] = defaultdict(list)
    for run in select(runs, args):
        for event in load_events(run):
            if event["kind"] == "error":
                grouped[(run["script"], event["error_type"])].append((run, event))
    if not grouped:
        print("No errors recorded.")
        return 0
    for (script, error_type), hits in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        print(f"\n{script} — {error_type} ×{len(hits)}")
        last_run, last_event = hits[-1]
        print(f"  latest: {last_run['run_id']}")
        print(f"  {last_event['message']}")
        if args.traceback:
            print("".join(f"    {line}\n" for line in last_event["traceback"].splitlines()))
    print(f"\n`runs.py show <run-id>` for the full trajectory of any of these.")
    return 0


def cmd_show(runs: list[dict], args) -> int:
    run = resolve(runs, args.run)
    if run is None:
        print(f"No run matching {args.run!r}. `runs.py` lists what's recorded.")
        return 1
    print(f"{run['run_id']}  [{run['status']}]  {run['duration_s']}s\n")
    for event in load_events(run):
        kind = event["kind"]
        if kind == "run_start":
            argv = " ".join(event.get("argv") or []) or "(no args)"
            dirty = " +dirty" if event.get("git_dirty") else ""
            print(f"  args: {argv}")
            print(f"  code: {event.get('git_sha')}{dirty}   python {event.get('python')}")
            if event.get("skill"):
                print(f"  skill: {event['skill']}")
            print()
        elif kind in {"stdout", "stderr"}:
            prefix = "  " if kind == "stdout" else "! "
            print(f"{prefix}{event['text']}")
        elif kind == "llm":
            usage = event.get("usage") or {}
            tokens = f"{usage.get('total_tokens', '?')} tok" if usage else "no usage"
            state = event.get("error") or f"{tokens}, {event.get('latency_s')}s"
            print(f"\n  [llm {event.get('purpose') or ''} {event.get('model')}] {state}")
            if args.prompts:
                print(f"    system: {event['system']}")
                print(f"    user:   {event['user']}")
            if event.get("response"):
                print(f"    -> {event['response']}")
            print()
        elif kind == "error":
            print(f"\n  [error] {event['error_type']}: {event['message']}")
            print("".join(f"    {line}\n" for line in event["traceback"].splitlines()))
        elif kind == "run_end":
            print(f"\n  [{event['status']}] exit {event['exit_code']} in {event['duration_s']}s")
        else:
            fields = {k: v for k, v in event.items() if k not in {"seq", "ts", "kind"}}
            print(f"  [{kind}] {json.dumps(fields, ensure_ascii=False)}")
    return 0


def cmd_llm(runs: list[dict], args) -> int:
    calls = [(r, e) for r in select(runs, args) for e in load_events(r) if e["kind"] == "llm"]
    if not calls:
        print("No LLM calls recorded.")
        return 0
    total = Counter()
    for run, call in calls:
        usage = call.get("usage") or {}
        total["prompt"] += usage.get("prompt_tokens", 0)
        total["completion"] += usage.get("completion_tokens", 0)
        total["calls"] += 1
        state = call.get("error") or f"{usage.get('total_tokens', '?')} tok"
        print(f"\n{run['run_id']}  {call.get('purpose')}  [{state}]")
        if args.full:
            print(f"  system: {call['system']}")
            print(f"  user:   {call['user']}")
        if call.get("response"):
            print(f"  -> {call['response']}")
    print(
        f"\n{total['calls']} call(s): {total['prompt']} prompt + {total['completion']} completion "
        f"= {total['prompt'] + total['completion']} tokens"
    )
    return 0


def cmd_summary(runs: list[dict], args) -> int:
    chosen = select(runs, args)
    if not chosen:
        print("No runs recorded yet.")
        return 0
    by_script: dict[str, Counter] = defaultdict(Counter)
    durations: dict[str, list[float]] = defaultdict(list)
    outcomes: Counter = Counter()
    tokens = 0
    for run in chosen:
        by_script[run["script"]][run["status"]] += 1
        durations[run["script"]].append(run["duration_s"])
        for event in load_events(run):
            if event["kind"] == "llm":
                tokens += (event.get("usage") or {}).get("total_tokens", 0)
            elif event["kind"] == "outreach_send":
                outcomes[f"outreach {'sent' if event['sent'] else 'not sent'}: {event['outcome']}"] += 1
            elif event["kind"] in {"outreach_skip", "followup_outcome"}:
                outcomes[f"{event['kind']}: {event.get('reason') or event.get('outcome')}"] += 1

    print(f"{len(chosen)} run(s) across {len(by_script)} script(s)\n")
    for script in sorted(by_script):
        counts = by_script[script]
        bad = sum(v for k, v in counts.items() if k != "ok")
        avg = sum(durations[script]) / len(durations[script])
        health = f"{counts['ok']} ok" + (f", {bad} not ok" if bad else "")
        print(f"  {script:<26} {health:<22} avg {avg:>6.1f}s")
    if outcomes:
        print("\nPer-item outcomes")
        for label, n in outcomes.most_common():
            print(f"  {n:>4}  {label}")
    if tokens:
        print(f"\nDrafting model: {tokens} tokens across these runs")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--script", help="Only runs of this script, e.g. send_outreach")
    parser.add_argument("--skill", help="Only runs driven by this skill, e.g. publish-paper-outreach")
    parser.add_argument("--limit", type=int, default=20, help="Most recent N runs (0 for all)")
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="Recent runs, newest last (the default)")
    p_list.add_argument("--failed", action="store_true", help="Only runs that did not end ok")

    p_errors = sub.add_parser("errors", help="Every recorded error, grouped by script and type")
    p_errors.add_argument("--traceback", action="store_true", help="Include the latest traceback of each group")

    p_show = sub.add_parser("show", help="Replay one run in order")
    p_show.add_argument("run", nargs="?", default="last", help="Run id, unique prefix, script name, or 'last'")
    p_show.add_argument("--prompts", action="store_true", help="Include full LLM prompts, not just responses")

    p_llm = sub.add_parser("llm", help="LLM calls and token usage")
    p_llm.add_argument("--full", action="store_true", help="Include full prompts and responses")

    sub.add_parser("summary", help="Per-script health, per-item outcomes, token spend")

    args = parser.parse_args()
    if args.limit == 0:
        args.limit = None

    runs = load_index()
    handlers = {
        None: cmd_list, "list": cmd_list, "errors": cmd_errors,
        "show": cmd_show, "llm": cmd_llm, "summary": cmd_summary,
    }
    return handlers[args.command](runs, args)


if __name__ == "__main__":
    raise SystemExit(main())
