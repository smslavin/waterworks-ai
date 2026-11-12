"""Logging setup shared by every waterworks-ai service.

Each service used to carry its own copy of this (gh-29): a logs/ directory
next to the service, a 5 MB x 3 rotating file, and the console. A service
appends the repo root to sys.path and calls setup_logging() once at import:

    sys.path.append(str(Path(__file__).resolve().parents[1]))  # repo root
    from service_logging import setup_logging

    setup_logging(__file__, "audit_mcp")

Stopgap until fieldworks-core ships the helper every Fieldworks service
needs (fieldworks-build/fieldworks-core#40); replace this module with it then.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TextIO

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 3


def setup_logging(
    service_file: str | Path,
    log_name: str,
    *,
    level: int = logging.INFO,
    console: TextIO | None = None,
) -> Path:
    """Log to <service dir>/logs/<log_name>.log and to the console.

    `service_file` is the calling module's __file__. `console` defaults to
    stderr (Python's default); chat-ui passes stdout, which the Windows
    service wrapper captures to a different file. Returns the log path.
    """
    log_dir = Path(service_file).resolve().parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"{log_name}.log"
    formatter = logging.Formatter(FORMAT, datefmt=DATEFMT)
    file_handler = RotatingFileHandler(
        log_path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT
    )
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler(console or sys.stderr)
    console_handler.setFormatter(formatter)
    logging.basicConfig(level=level, handlers=[console_handler, file_handler])
    return log_path
