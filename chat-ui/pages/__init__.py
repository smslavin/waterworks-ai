"""Server-rendered pages: the audit log (/audit) and metrics (/metrics).

Moved out of backend.py (gh-29), where they were whole HTML documents in
f-strings, ~35% of that file. Every value from the audit log, the metrics
DB or the request goes through esc(): the old pages interpolated tool
results, model responses and user messages raw, so any of them containing
markup ran in the operator's browser.
"""

from html import escape
from pathlib import Path

_DIR = Path(__file__).parent


def esc(value) -> str:
    """HTML-escape anything for text or a quoted attribute."""
    return escape("" if value is None else str(value), quote=True)


def asset(name: str) -> str:
    """A CSS or JS file from this package, inlined into a page."""
    return (_DIR / name).read_text()
