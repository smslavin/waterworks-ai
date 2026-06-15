"""File-based specialist memory — one markdown file per specialist.

Gitignored. Specialists read at session start, append at session end.
Safe for concurrent asyncio access (event loop is single-threaded, opens
in append mode).
"""

import os
from datetime import datetime, timezone
from pathlib import Path

_MEM_DIR = Path(os.environ.get("SPECIALIST_MEMORY_DIR", "../data/specialist-memory"))


def _path(specialist: str) -> Path:
    _MEM_DIR.mkdir(parents=True, exist_ok=True)
    return _MEM_DIR / f"{specialist}.md"


def get_specialist_memory(specialist: str) -> str:
    p = _path(specialist)
    return p.read_text() if p.exists() else ""


def append_specialist_memory(specialist: str, content: str) -> None:
    p = _path(specialist)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    with open(p, "a") as f:
        f.write(f"\n## {ts}\n{content.strip()}\n")
