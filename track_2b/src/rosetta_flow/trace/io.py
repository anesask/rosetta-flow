"""JSONL storage: one trace or label per line, UTF-8, non-ASCII kept readable."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path

from pydantic import BaseModel


def write_jsonl[M: BaseModel](path: Path, items: Iterable[M]) -> int:
    """Atomic: written to a temp file and renamed, so a crash never leaves a truncated dataset behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    n = 0
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        for item in items:
            f.write(item.model_dump_json(exclude_none=True) + "\n")
            n += 1
    os.replace(tmp, path)
    return n


MAX_LINE_CHARS = 20_000_000  # one trace per line; anything bigger is not a trace an auditor should load


def index_by[T](items: Iterable[T], key: Callable[[T], str], source: object) -> dict[str, T]:
    """Items by id. Duplicate ids are an error: silently keeping the last one would audit or score one run and
    drop the other without a trace."""
    out: dict[str, T] = {}
    for item in items:
        k = key(item)
        if k in out:
            raise ValueError(f"{source}: duplicate id {k!r}")
        out[k] = item
    return out


def read_jsonl[M: BaseModel](path: Path, model: type[M]) -> Iterator[M]:
    with path.open(encoding="utf-8") as f:
        lineno = 0
        try:
            for lineno, line in enumerate(f, 1):
                if len(line) > MAX_LINE_CHARS:
                    raise ValueError(f"{path}:{lineno}: line longer than {MAX_LINE_CHARS} characters")
                if line.strip():
                    try:
                        yield model.model_validate_json(line)
                    except ValueError as e:
                        raise ValueError(f"{path}:{lineno}: {e}") from e
        except UnicodeDecodeError as e:
            raise ValueError(f"{path}:{lineno + 1}: file is not UTF-8 ({e.reason}); re-save it as UTF-8") from e
