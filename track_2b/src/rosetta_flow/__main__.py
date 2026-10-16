"""Entry point for `make run`: check that the configured model answers, then serve the web app.

Without a reachable model the app still serves the precomputed audits; only live audits are off.
"""

from __future__ import annotations

import os
import sys
import time

import openai
from dotenv import find_dotenv, load_dotenv

from rosetta_flow import __version__
from rosetta_flow.llm import LLMConfig, chat, redact

_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _ansi(code: str):
    return (lambda s: f"\033[{code}m{s}\033[0m") if _COLOR else str


bold, dim, green, red = _ansi("1"), _ansi("2"), _ansi("32"), _ansi("31")


def _row(key: str, value: str) -> None:
    print(f"  {dim(f'{key:<9}')} {value}")


def check_model() -> LLMConfig | None:
    try:
        cfg = LLMConfig.from_env()
    except RuntimeError as e:
        _row("model", f"{red('not configured')} {e}")
        return None
    _row("model", cfg.name)
    _row("endpoint", cfg.base_url)
    t0 = time.perf_counter()
    try:
        # A short timeout: a judge with a wrong endpoint should see the error in seconds, not after 4 x 300 s.
        chat(cfg, [{"role": "user", "content": "Reply with exactly: pong"}], max_tokens=5, temperature=0, timeout=30)
    except openai.APIError as e:
        _row("status", f"{red('unreachable')} {redact(str(e))}")
        return None
    _row("status", f"{green('ok')} model answered in {time.perf_counter() - t0:.1f}s")
    return cfg


def main() -> int:
    load_dotenv(find_dotenv(usecwd=True))
    print(f"{bold('rosetta-flow')} {dim(__version__)}")
    cfg = check_model()
    if cfg is None:
        _row("live", "off: the app shows precomputed audits only")

    import uvicorn

    from rosetta_flow.app.server import create_app

    port = int(os.environ.get("PORT", "8000"))
    _row("open", bold(f"http://localhost:{port}"))
    uvicorn.run(create_app(cfg=cfg), host=os.environ.get("HOST", "127.0.0.1"), port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
