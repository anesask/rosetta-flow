"""Resumable parallel batches. Each finished item is appended to a progress file at once, so a crash or Ctrl+C
loses at most the items in flight, and --resume redoes only what is missing (failed items included)."""

from __future__ import annotations

import itertools
import json
import sys
import threading
from collections.abc import Callable, Hashable, Iterable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rosetta_flow.llm import redact, tokens_spent

Record = dict[str, Any]


def load_records(path: Path, key_of: Callable[[Record], Hashable]) -> dict[Hashable, Record]:
    done: dict[Hashable, Record] = {}
    if not path.exists():
        return done
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
                done[key_of(rec)] = rec
            except (json.JSONDecodeError, KeyError, TypeError):
                continue  # a line cut off by a crash; that item is simply done again
    return done


@dataclass
class BatchOutcome[K: Hashable]:
    done: dict[K, Record]
    failures: list[Record]
    tokens: int = 0  # spent by this invocation (resumed items not counted)
    stopped_by_budget: bool = False


def run_batch[K: Hashable, R](
    keys: Iterable[K],
    work: Callable[[K], R],
    progress: Path,
    *,
    to_record: Callable[[R], Record],
    key_of: Callable[[Record], K],
    resume: bool = False,
    workers: int = 4,
    on_done: Callable[[K, Record], None] | None = None,
    tokens_of: Callable[[Record], int] | None = None,
    max_tokens: int | None = None,
) -> BatchOutcome[K]:
    """Run work(key) for every key not yet in the progress file.

    With max_tokens, no new item starts once the tokens spent by this invocation reach the budget; items already
    running finish and are saved, so a stopped run is continued with --resume (and a higher budget if needed).
    """
    progress.parent.mkdir(parents=True, exist_ok=True)
    if progress.exists() and not resume:
        raise SystemExit(f"{progress} exists: pass --resume to continue it, or choose a new --out")
    done: dict[K, Record] = load_records(progress, key_of) if resume else {}  # type: ignore[assignment]
    if done:
        print(f"resuming: {len(done)} items already done")
    outcome = BatchOutcome(done, [])
    todo = iter([k for k in keys if k not in done])
    lock = threading.Lock()

    spent_before = tokens_spent()

    def spent() -> int:
        # Records only carry successful items; the process counter also sees items that failed after spending.
        return max(outcome.tokens, tokens_spent() - spent_before)

    def over_budget() -> bool:
        return max_tokens is not None and spent() >= max_tokens

    pool = ThreadPoolExecutor(max_workers=max(1, workers))
    try:
        with progress.open("a", encoding="utf-8", newline="\n") as log:
            # Submit lazily, at most `workers` ahead, so the budget check sees spending before new work starts.
            running: dict = {}
            for key in itertools.islice(todo, max(1, workers)):
                running[pool.submit(work, key)] = key
            while running:
                finished, _ = wait(running, return_when=FIRST_COMPLETED)
                for fut in finished:
                    key = running.pop(fut)
                    try:
                        rec = to_record(fut.result())
                    except Exception as e:  # one broken item must not kill the batch
                        error = redact(repr(e))
                        outcome.failures.append({"key": key, "error": error})
                        print(f"  [{key}] failed: {error}", file=sys.stderr)
                    else:
                        with lock:
                            log.write(json.dumps(rec, ensure_ascii=False) + "\n")
                            log.flush()
                            done[key] = rec
                            outcome.tokens += tokens_of(rec) if tokens_of else 0
                        if on_done:
                            on_done(key, rec)
                    if over_budget():
                        outcome.stopped_by_budget = True
                    elif (nxt := next(todo, None)) is not None:
                        running[pool.submit(work, nxt)] = nxt
    except KeyboardInterrupt:
        pool.shutdown(wait=False, cancel_futures=True)
        print(f"\ninterrupted: {len(done)} items saved in {progress}, continue with --resume", file=sys.stderr)
        raise
    pool.shutdown()
    outcome.tokens = spent()
    if outcome.stopped_by_budget:
        print(
            f"stopped: token budget of {max_tokens:,} reached ({outcome.tokens:,} spent); "
            "continue with --resume and a higher --max-tokens",
            file=sys.stderr,
        )
    return outcome


def write_records(path: Path, records: Iterable[Record]) -> None:
    """Atomic JSONL write of plain dict records."""
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    """UTF-8 with LF line endings on every platform (Path.write_text writes CRLF on Windows)."""
    path.write_text(text, encoding="utf-8", newline="\n")
