"""InfluxDB MCP server — read and write InfluxDB via AI-callable tools.

Tools
-----
list_measurements   Discover what measurements exist in a bucket. Returns org,
                    bucket, and measurement list — enough context to build queries.
write_point         Write a single tagged data point.
query               Run an arbitrary Flux query; returns formatted results.

Environment variables
---------------------
INFLUXDB_URL     InfluxDB endpoint        (default: http://localhost:8086)
INFLUXDB_TOKEN   Admin or write token     (required)
INFLUXDB_ORG     Organisation name        (default: waterworks)
INFLUXDB_BUCKET  Default bucket           (default: waterworks)
FASTMCP_PORT     Port this server binds   (default: 8003)
"""

import json
import logging
import logging.handlers
import os
from typing import Any

from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from mcp.server.fastmcp import FastMCP

load_dotenv()

_log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_log_dir, exist_ok=True)
_fh = logging.handlers.RotatingFileHandler(
    os.path.join(_log_dir, "influxdb_mcp.log"), maxBytes=5 * 1024 * 1024, backupCount=3
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

INFLUXDB_URL = os.environ.get("INFLUXDB_URL", "http://localhost:8086")
INFLUXDB_TOKEN = os.environ.get("INFLUXDB_TOKEN", "")
INFLUXDB_ORG = os.environ.get("INFLUXDB_ORG", "waterworks")
INFLUXDB_BUCKET = os.environ.get("INFLUXDB_BUCKET", "waterworks")

mcp = FastMCP("influxdb-mcp", port=int(os.environ.get("FASTMCP_PORT", 8003)))

# Single client instance for the lifetime of the process.
_client: InfluxDBClient | None = None


def _get_client() -> InfluxDBClient:
    global _client
    if _client is None:
        _client = InfluxDBClient(
            url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG
        )
    return _client


def _format_tables(tables: list) -> str:
    """Render FluxTable query results as a readable text block."""
    if not tables:
        return "No results."

    lines: list[str] = []
    for table in tables:
        for record in table.records:
            parts: list[str] = []
            t = record.get_time()
            if t:
                parts.append(f"time={t.isoformat()}")
            m = record.get_measurement()
            if m:
                parts.append(f"measurement={m}")
            field = record.get_field()
            value = record.get_value()
            if field is not None:
                parts.append(f"{field}={value}")
            elif value is not None:
                parts.append(f"value={value}")
            for k, v in record.values.items():
                if not k.startswith("_") and k not in ("table", "result"):
                    parts.append(f"{k}={v}")
            lines.append("  " + "  ".join(parts))

    return f"{len(lines)} record(s):\n" + "\n".join(lines)


# ── Tools ─────────────────────────────────────────────────────────────────────


@mcp.tool()
def list_measurements(bucket: str = "") -> str:
    """List all measurements in an InfluxDB bucket.

    Returns the configured org and bucket name alongside the measurement list
    so you have the context needed to construct Flux queries.

    Args:
        bucket: Bucket to inspect. Omit to use the configured default bucket.
    """
    target = bucket or INFLUXDB_BUCKET
    flux = (
        'import "influxdata/influxdb/schema"\n'
        f'schema.measurements(bucket: "{target}")'
    )
    try:
        tables = _get_client().query_api().query(flux, org=INFLUXDB_ORG)
        measurements = [r.get_value() for t in tables for r in t.records]
        return json.dumps(
            {
                "url": INFLUXDB_URL,
                "org": INFLUXDB_ORG,
                "bucket": target,
                "measurements": measurements,
            },
            indent=2,
        )
    except Exception as exc:
        return f"Error: {exc}"


@mcp.tool()
def write_point(
    measurement: str,
    fields: dict[str, Any],
    tags: dict[str, str] | None = None,
    bucket: str = "",
) -> str:
    """Write a single tagged data point to InfluxDB.

    Args:
        measurement: Measurement name, e.g. "pump_metrics" or "ai_metrics".
        fields:      Field name → value pairs. Numeric values are stored as
                     floats; string values as strings.
        tags:        Optional tag name → string value pairs. Tags are indexed
                     and used for filtering, e.g. {"instance": "RawWater_01",
                     "type": "Pump"}.
        bucket:      Target bucket. Omit to use the configured default bucket.
    """
    target = bucket or INFLUXDB_BUCKET
    try:
        point = Point(measurement)
        for k, v in (tags or {}).items():
            point = point.tag(k, v)
        for k, v in fields.items():
            point = point.field(k, v)
        _get_client().write_api(write_options=SYNCHRONOUS).write(
            bucket=target, record=point
        )
        tag_str = ", ".join(f"{k}={v}" for k, v in (tags or {}).items())
        field_str = ", ".join(f"{k}={v}" for k, v in fields.items())
        return (
            f"Written  bucket={target}  measurement={measurement}"
            + (f"  tags=[{tag_str}]" if tag_str else "")
            + f"  fields=[{field_str}]"
        )
    except Exception as exc:
        return f"Error: {exc}"


@mcp.tool()
def query(flux_query: str, org: str = "") -> str:
    """Run a Flux query against InfluxDB and return formatted results.

    Call list_measurements() first to discover available buckets, measurements,
    and field names. Bucket and org are embedded in the query itself:

        from(bucket: "waterworks")
          |> range(start: -1h)
          |> filter(fn: (r) => r._measurement == "pump_metrics")
          |> filter(fn: (r) => r.instance == "RawWater_01")
          |> filter(fn: (r) => r._field == "Flow")
          |> last()

    Args:
        flux_query: Full Flux query string.
        org:        InfluxDB org. Omit to use the configured default org.
    """
    try:
        tables = _get_client().query_api().query(flux_query, org=org or INFLUXDB_ORG)
        return _format_tables(tables)
    except KeyError as exc:
        return (
            f"Error: result is missing column {exc}. "
            "Functions like count(), distinct(), schema.tagValues(), and schema.fieldKeys() "
            "remove _time from results. Use last() to get recent values, or "
            "aggregateWindow(every: 1h, fn: count, createEmpty: false) for time-series counts."
        )
    except Exception as exc:
        return f"Error: {exc}"


if __name__ == "__main__":
    mcp.run(transport="sse")
