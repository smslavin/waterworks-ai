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

import asyncio
import json
import logging
import logging.handlers
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from mcp.server import MCPServer

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "chat-ui"))
from mcp_client import call_mcp_tool
from plant_registry import load_sites

load_dotenv()

_log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_log_dir, exist_ok=True)
_fh = logging.handlers.RotatingFileHandler(
    os.path.join(_log_dir, "query_history_mcp.log"),
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
)
_fh.setFormatter(
    logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(), _fh],
)
logger = logging.getLogger(__name__)

mcp = MCPServer("query-history-mcp")


async def _query_one_plant(
    site_id: str, site: dict, start: str, end: str, equipment: str
) -> list[dict]:
    aggregator_url = site.get("aggregator_url")
    if not aggregator_url:
        logger.warning(
            "query_enterprise_history(%s): no aggregator_url in enterprise.yaml, skipping",
            site_id,
        )
        return []
    try:
        raw = await call_mcp_tool(
            "audit__query_history",
            {"start": start, "end": end, "equipment": equipment},
            aggregator_url,
        )
        data = json.loads(raw)
    except Exception as exc:
        logger.warning("query_enterprise_history(%s) failed: %s", site_id, exc)
        return []

    sessions = data.get("sessions") if isinstance(data, dict) else None
    if not isinstance(sessions, list):
        logger.warning(
            "query_enterprise_history(%s): unexpected response shape: %s",
            site_id,
            raw[:200],
        )
        return []
    return sessions


@mcp.tool()
async def query_enterprise_history(
    start: str, end: str, site_id: str = "", equipment: str = ""
) -> str:
    """Cross-plant diagnostic session history for a time range, merged from
    every registered plant's own audit-mcp (federated read — each plant's
    metrics.db stays authoritative for its own rows, nothing is replicated).

    Args:
        start:     ISO datetime string for range start (e.g. "2026-08-09T00:00:00Z")
        end:       ISO datetime string for range end   (e.g. "2026-08-09T23:59:59Z")
        site_id:   Optional — restrict to one plant (e.g. "wtp2"). Omit for all.
        equipment: Optional equipment ID filter (e.g. "RawWater_01"), passed
                   through to each plant's own query_history.
    """
    sites = load_sites()
    if site_id:
        if site_id not in sites:
            known = ", ".join(sorted(sites.keys())) or "(none registered)"
            return json.dumps(
                {"error": f"unknown site_id '{site_id}'. Known sites: {known}."}
            )
        sites = {site_id: sites[site_id]}

    if not sites:
        return json.dumps(
            {"sessions": [], "message": "No sites registered in enterprise.yaml."}
        )

    per_plant_results = await asyncio.gather(
        *(
            _query_one_plant(sid, site, start, end, equipment)
            for sid, site in sites.items()
        )
    )
    merged: list[dict] = []
    for sessions in per_plant_results:
        merged.extend(sessions)
    merged.sort(key=lambda s: s.get("ts", ""))

    return json.dumps(
        {
            "range": {"start": start, "end": end},
            "site_id": site_id or "all",
            "equipment": equipment or "all",
            "sessions": merged,
        },
        indent=2,
        default=str,
    )


if __name__ == "__main__":
    mcp.run(transport="sse", port=int(os.environ.get("FASTMCP_PORT", 8201)))
