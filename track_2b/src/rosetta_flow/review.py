"""Human review of findings (optional component): a reviewer marks each finding as confirmed, a false alarm, or to
follow up. Decisions go to an append-only JSONL log in which every entry carries the hash of the one before, so a
later edit or deletion breaks the chain and `verify` reports where. This is the audit trail that human oversight
of AI (FINMA guidance, EU AI Act) asks for, and the decisions double as labels from real use.
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

DECISIONS = ("confirmed", "false_alarm", "follow_up")
GENESIS = "0" * 64
MAX_NOTE = 500


@dataclass(frozen=True)
class Review:
    at: str
    trace_id: str
    finding: int
    decision: str
    reviewer: str
    note: str
    prev: str
    hash: str


def _digest(prev: str, fields: dict[str, object]) -> str:
    body = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{prev}\n{body}".encode()).hexdigest()


def _fields(r: Review) -> dict[str, object]:
    return {k: v for k, v in asdict(r).items() if k not in ("prev", "hash")}


class ReviewLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def entries(self) -> list[Review]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as f:
            return [Review(**json.loads(line)) for line in f if line.strip()]

    def add(self, trace_id: str, finding: int, decision: str, reviewer: str, note: str = "") -> Review:
        if decision not in DECISIONS:
            raise ValueError(f"decision must be one of {DECISIONS}")
        if not reviewer.strip():
            raise ValueError("reviewer is required: the trail records who decided")
        if finding < 0:
            raise ValueError("finding index must be >= 0")
        with self._lock:
            entries = self.entries()
            prev = entries[-1].hash if entries else GENESIS
            fields = {"at": datetime.now(UTC).isoformat(timespec="seconds"), "trace_id": trace_id,
                      "finding": finding, "decision": decision, "reviewer": reviewer.strip(),
                      "note": " ".join(note.split())[:MAX_NOTE]}  # fmt: skip
            review = Review(**fields, prev=prev, hash=_digest(prev, fields))  # type: ignore[arg-type]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(asdict(review), ensure_ascii=False) + "\n")
            return review

    def latest(self) -> dict[tuple[str, int], Review]:
        """The newest decision per finding: a reviewer may revise, and the trail keeps every earlier decision."""
        return {(r.trace_id, r.finding): r for r in self.entries()}

    def verify(self) -> int | None:
        """Index of the first entry that breaks the hash chain, or None if the log is intact."""
        prev = GENESIS
        for i, r in enumerate(self.entries()):
            if r.prev != prev or r.hash != _digest(prev, _fields(r)):
                return i
            prev = r.hash
        return None
