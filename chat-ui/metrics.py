"""AI_Metrics writer — logs per-turn telemetry to InfluxDB measurement ai_metrics."""

import logging
import os

from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

load_dotenv()

INFLUXDB_URL    = os.environ.get("INFLUXDB_URL",    "http://localhost:8086")
INFLUXDB_TOKEN  = os.environ.get("INFLUXDB_TOKEN",  "")
INFLUXDB_ORG    = os.environ.get("INFLUXDB_ORG",    "waterworks")
INFLUXDB_BUCKET = os.environ.get("INFLUXDB_BUCKET", "waterworks")

logger = logging.getLogger(__name__)

_client: InfluxDBClient | None = None


def _get_client() -> InfluxDBClient:
    global _client
    if _client is None:
        _client = InfluxDBClient(
            url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG
        )
    return _client


def log_turn(
    *,
    session_id: str,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    tool_call_count: int,
    error_count: int,
    latency_ms: int,
    user_message: str,
) -> None:
    try:
        point = (
            Point("ai_metrics")
            .tag("model", model)
            .tag("session_id", session_id)
            .field("input_tokens",    int(input_tokens  or 0))
            .field("output_tokens",   int(output_tokens or 0))
            .field("tool_call_count", int(tool_call_count))
            .field("error_count",     int(error_count))
            .field("latency_ms",      int(latency_ms))
            .field("user_message",    (user_message or "")[:200])
        )
        _get_client().write_api(write_options=SYNCHRONOUS).write(
            bucket=INFLUXDB_BUCKET, record=point
        )
    except Exception as exc:
        # Metrics are best-effort — never let a write failure break the chat loop.
        logger.warning("Metrics write failed: %s", exc)
