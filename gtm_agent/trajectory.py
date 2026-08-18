"""Append-only run trajectories, for after-the-fact error analysis.

Every script run writes one JSONL file under `runs/`: what was invoked, what
it printed, every LLM call with its prompts and token usage, per-item
outcomes, and the traceback if it died. `gtm_agent/runs.py` reads them back.

Two deliberate choices. JSONL files rather than a table in `gtm_agent.db`,
because the point of these is to be re-read later — by grep, or by handing a
run straight to a model and asking what went wrong — and a run is a story in
order, not a set of rows. And stdout is teed wholesale rather than every
`print` being replaced by a structured event: the scripts already narrate
themselves well, so capturing that narration costs one line per script
instead of a rewrite of all of them.

Logging is best-effort throughout. A trajectory that fails to write must
never take a real send down with it, so every entry point here swallows its
own errors and carries on.
"""

import json
import os
import subprocess
import sys
import time
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

RUNS_DIR = Path(os.environ.get("GTM_RUNS_DIR", "runs"))
INDEX_NAME = "index.jsonl"

_OFF_VALUES = {"0", "false", "off", "no"}
_current: "Run | None" = None
_git_revision: "tuple[str | None, bool] | None" = None


# Which pipeline a script belongs to, so runs group by the skill that drives
# them without every skill having to remember to export GTM_SKILL. Inferred,
# and recorded as such — GTM_SKILL always wins when it is set.
SCRIPT_SKILL = {
    "check_mentions": "discover-and-draft-x-replies",
    "discover": "discover-and-draft-x-replies",
    "discover_accounts": "discover-and-draft-x-replies",
    "harvest_and_rank": "discover-and-draft-x-replies",
    "export_linkedin_leads": "publish-paper-outreach",
    "fetch_paper_authors": "paper-outreach",
    "research_authors": "paper-outreach",
    "send_followups": "publish-paper-outreach",
    "post_all_due": "publish-x-queue",
    "post_ready": "publish-x-queue",
    "sync_posted": "publish-x-queue",
    "sync_typefully_status": "publish-x-queue",
    "post_response_calendar": "publish-x-replies",
    "sync_replies": "publish-x-replies",
}


def _skill(script: str, argv: list[str]) -> tuple[str | None, str]:
    from_env = os.environ.get("GTM_SKILL")
    if from_env:
        return from_env, "env"
    if script == "send_outreach":
        # The one script two skills share, told apart by the flag paper-outreach
        # always passes and publish-paper-outreach never does.
        return ("paper-outreach" if "--draft-only" in argv else "publish-paper-outreach"), "inferred"
    return SCRIPT_SKILL.get(script), "inferred"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _enabled() -> bool:
    return os.environ.get("GTM_TRAJECTORY", "1").strip().lower() not in _OFF_VALUES


def _git_state() -> tuple[str | None, bool]:
    """Commit the run executed on, and whether the tree was dirty. Worth
    recording because this repo is routinely run with uncommitted edits, and
    "which code produced this output" is otherwise unanswerable later."""
    global _git_revision
    if _git_revision is None:
        try:
            sha = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=5, check=True,
            ).stdout.strip()
            dirty = bool(subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, timeout=5, check=True,
            ).stdout.strip())
            _git_revision = (sha, dirty)
        except (OSError, subprocess.SubprocessError):
            _git_revision = (None, False)
    return _git_revision


class Run:
    """One script invocation. Owns an open JSONL file until `finish`."""

    def __init__(self, script: str):
        started = datetime.now(timezone.utc)
        self.script = script
        self.skill: str | None = None
        self.run_id = f"{started.strftime('%Y%m%d-%H%M%S')}-{script}-{uuid.uuid4().hex[:4]}"
        self.started_at = started
        self.path = RUNS_DIR / started.strftime("%Y-%m-%d") / f"{self.run_id}.jsonl"
        self.counts: dict[str, int] = {}
        self._seq = 0
        self._monotonic = time.monotonic()
        self._file = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = self.path.open("a", encoding="utf-8")
        except OSError:
            self._file = None

    def write(self, kind: str, **fields) -> None:
        self.counts[kind] = self.counts.get(kind, 0) + 1
        if self._file is None:
            return
        self._seq += 1
        record = {"seq": self._seq, "ts": _now(), "kind": kind, **fields}
        try:
            self._file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            self._file.flush()  # a crashed run must still leave its trajectory behind
        except (OSError, TypeError, ValueError):
            pass

    def error(self, exc: BaseException) -> None:
        self.write(
            "error",
            error_type=type(exc).__name__,
            message=str(exc),
            traceback="".join(traceback.format_exception(exc)),
        )

    def finish(self, status: str, exit_code: int) -> None:
        duration = round(time.monotonic() - self._monotonic, 3)
        summary = {
            "run_id": self.run_id,
            "script": self.script,
            "skill": self.skill,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "status": status,
            "exit_code": exit_code,
            "duration_s": duration,
            "counts": dict(self.counts),
            "path": str(self.path),
        }
        self.write("run_end", **{k: v for k, v in summary.items() if k not in {"run_id", "script", "skill"}})
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None
        try:
            index = RUNS_DIR / INDEX_NAME
            index.parent.mkdir(parents=True, exist_ok=True)
            with index.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
        except OSError:
            pass


class _Tee:
    """Mirrors a stream to the terminal and into the trajectory, a line at a
    time. Partial lines are held back so a `print(..., end="")` progress dot
    doesn't become its own event."""

    def __init__(self, stream, run: Run, name: str):
        self._stream = stream
        self._run = run
        self._name = name
        self._buffer = ""

    def write(self, text: str) -> int:
        written = self._stream.write(text)
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self._run.write(self._name, text=line)
        return written

    def flush(self) -> None:
        self._stream.flush()

    def drain(self) -> None:
        if self._buffer.strip():
            self._run.write(self._name, text=self._buffer)
        self._buffer = ""

    def __getattr__(self, name):
        return getattr(self._stream, name)


def run_main(main, script_file: str) -> int:
    """Wrap a script's `main()` so the whole invocation is recorded.

    Behaviour on failure is deliberately unchanged: the exception is logged
    and then re-raised, so the traceback still reaches the terminal and the
    exit code still comes from Python, not from here.
    """
    if not _enabled():
        return main()

    global _current
    script = Path(script_file).stem
    run = Run(script)
    _current = run
    sha, dirty = _git_state()
    skill, skill_source = _skill(script, sys.argv[1:])
    run.skill = skill
    run.write(
        "run_start",
        run_id=run.run_id,
        script=script,
        argv=sys.argv[1:],
        skill=skill,
        skill_source=skill_source,
        git_sha=sha,
        git_dirty=dirty,
        python=sys.version.split()[0],
        cwd=os.getcwd(),
        pid=os.getpid(),
    )

    out_tee = _Tee(sys.stdout, run, "stdout")
    err_tee = _Tee(sys.stderr, run, "stderr")
    sys.stdout, sys.stderr = out_tee, err_tee
    try:
        code = main() or 0
    except SystemExit as exc:
        # argparse's `--help` and its usage errors exit from inside main().
        # Neither is a crash, so they are recorded as an ordinary outcome.
        exit_code = exc.code if isinstance(exc.code, int) else 0
        _teardown(out_tee, err_tee, run, "ok" if exit_code == 0 else "failed", exit_code)
        raise
    except KeyboardInterrupt as exc:
        run.error(exc)
        _teardown(out_tee, err_tee, run, "interrupted", 130)
        raise
    except BaseException as exc:
        run.error(exc)
        _teardown(out_tee, err_tee, run, "crashed", 1)
        raise
    _teardown(out_tee, err_tee, run, "ok" if code == 0 else "failed", code)
    return code


def _teardown(out_tee: _Tee, err_tee: _Tee, run: Run, status: str, exit_code: int) -> None:
    global _current
    out_tee.drain()
    err_tee.drain()
    sys.stdout, sys.stderr = out_tee._stream, err_tee._stream
    run.finish(status, exit_code)
    _current = None


def log(kind: str, **fields) -> None:
    """Record a structured event on the active run. A no-op outside one, so
    library code can call it without caring how it was invoked."""
    if _current is not None:
        _current.write(kind, **fields)


def log_llm(
    model: str,
    system: str,
    user: str,
    response: str | None = None,
    usage: dict | None = None,
    latency_s: float | None = None,
    error: str | None = None,
    **fields,
) -> None:
    """Full prompt and completion, on purpose — a draft can only be judged
    later against the prompt that produced it."""
    log(
        "llm",
        model=model,
        system=system,
        user=user,
        response=response,
        usage=usage or {},
        latency_s=latency_s,
        error=error,
        **fields,
    )


@contextmanager
def step(name: str, **fields):
    """Time a named phase of a run, recording it even when it raises."""
    started = time.monotonic()
    log("step_start", step=name, **fields)
    try:
        yield
    except BaseException as exc:
        log("step_end", step=name, status="error", error_type=type(exc).__name__,
            message=str(exc), duration_s=round(time.monotonic() - started, 3))
        raise
    log("step_end", step=name, status="ok", duration_s=round(time.monotonic() - started, 3))


def current_run_id() -> str | None:
    return _current.run_id if _current is not None else None
