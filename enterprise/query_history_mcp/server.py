"""query_enterprise_history MCP server — federated read across every plant's
own audit-mcp.

Tools
-----
query_enterprise_history   Cross-plant diagnostic session history for a time
                           range, merged from each plant's own audit-mcp
                           query_history tool.

This is a federated read, not a central store — consistent with the
per-plant-InfluxDB precedent from Phase 0. No replication: each plant's own
metrics.db stays the single source of truth for its own rows, this server
just fans a request out and merges the responses.

Unlike diagnose_plant_mcp (Phase 2), this server DOES call each plant's own
aggregator directly (see enterprise.yaml's header comment) — audit/history
data isn't raw sensor/control access, so it doesn't need the "never hold
aggregator credentials" guarantee that diagnose_plant_mcp exists to provide.

Environment variables
---------------------
ENTERPRISE_FILE  Path to enterprise.yaml (default: ../enterprise.yaml)
FASTMCP_PORT     Port to bind             (default: 8201)
"""

import json
import logging
import os
import sys
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from fieldworks.service_env import check_env_file
from mcp.server import MCPServer
from mcp.types import ToolAnnotations

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "chat-ui"))
from mcp_client import call_mcp_tool
from fieldworks.enterprise import (
    RegisteredSite,
    SiteUnavailable,
    UnknownSiteError,
    federated_read,
)
from plant_registry import load_sites

check_env_file(find_dotenv())  # before load_dotenv: see fieldworks.service_env
load_dotenv()

from fieldworks.service_logging import setup_logging  # noqa: E402

setup_logging(__file__, "query_history_mcp")
logger = logging.getLogger(__name__)

mcp = MCPServer("query-history-mcp")


# A plant's audit history query is a local SQLite read; anything slower than
# this is a plant in trouble, reported as unavailable rather than waited on.
PLANT_TIMEOUT_SECONDS = 30


async def _query_one_plant(
    site_id: str, site: RegisteredSite, start: str, end: str, equipment: str
) -> list[dict]:
    if not site.aggregator_url:
        raise SiteUnavailable("no aggregator_url in enterprise.yaml")
    raw = await call_mcp_tool(
        "audit__query_history",
        {"start": start, "end": end, "equipment": equipment},
        site.aggregator_url,
    )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # call_mcp_tool reports transport failures as an "Error ..." string.
        raise SiteUnavailable(raw[:200]) from None
    sessions = data.get("sessions") if isinstance(data, dict) else None
    if not isinstance(sessions, list):
        raise SiteUnavailable(f"unexpected response shape: {raw[:200]}")
    return sessions


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True))
async def query_enterprise_history(
    start: str, end: str, site_id: str = "", equipment: str = ""
) -> str:
    """Cross-plant diagnostic session history for a time range, merged from
    every registered plant's own audit-mcp (federated read — each plant's
    metrics.db stays authoritative for its own rows, nothing is replicated).
    Plants that didn't answer are listed under "unavailable": their history
    is unknown, not empty.

    Args:
        start:     ISO datetime string for range start (e.g. "2026-08-09T00:00:00Z")
        end:       ISO datetime string for range end   (e.g. "2026-08-09T23:59:59Z")
        site_id:   Optional — restrict to one plant (e.g. "wtp2"). Omit for all.
        equipment: Optional equipment ID filter (e.g. "RawWater_01"), passed
                   through to each plant's own query_history.
    """
    sites = load_sites()
    if not sites:
        return json.dumps(
            {"sessions": [], "message": "No sites registered in enterprise.yaml."}
        )

    async def fetch(sid: str, site: RegisteredSite) -> list[dict]:
        return await _query_one_plant(sid, site, start, end, equipment)

    try:
        result = await federated_read(
            sites, fetch, site_id=site_id or None, timeout=PLANT_TIMEOUT_SECONDS
        )
    except UnknownSiteError as exc:
        return json.dumps({"error": str(exc)})

    for sid, reason in result.unavailable.items():
        logger.warning("query_enterprise_history(%s) unavailable: %s", sid, reason)

    return json.dumps(
        {
            "range": {"start": start, "end": end},
            "site_id": site_id or "all",
            "equipment": equipment or "all",
            "sessions": result.records,
            "unavailable": result.unavailable,
            "complete": result.complete,
        },
        indent=2,
        default=str,
    )


if __name__ == "__main__":
    mcp.run(transport="sse", port=int(os.environ.get("FASTMCP_PORT", 8201)))
