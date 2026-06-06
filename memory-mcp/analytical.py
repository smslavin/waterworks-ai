"""DuckDB analytical layer — InfluxDB materialization pipeline + query tool.

One DuckDB connection is shared across the sync loop and query tool; both run
in the same process so single-writer constraint is satisfied.
"""

import asyncio
import os
from pathlib import Path

import duckdb
from influxdb_client import InfluxDBClient

_DUCKDB_PATH     = os.environ.get("DUCKDB_PATH",       "../data/duckdb/analytical.duckdb")
_INFLUXDB_URL    = os.environ.get("INFLUXDB_URL",      "http://localhost:8086")
_INFLUXDB_TOKEN  = os.environ.get("INFLUXDB_TOKEN",    "")
_INFLUXDB_ORG    = os.environ.get("INFLUXDB_ORG",      "waterworks")
_INFLUXDB_BUCKET = os.environ.get("INFLUXDB_BUCKET",   "waterworks")
_SYNC_INTERVAL   = int(os.environ.get("DUCKDB_SYNC_INTERVAL", "3600"))

_conn: duckdb.DuckDBPyConnection | None = None


def get_conn() -> duckdb.DuckDBPyConnection:
    global _conn
    if _conn is None:
        Path(_DUCKDB_PATH).parent.mkdir(parents=True, exist_ok=True)
        _conn = duckdb.connect(_DUCKDB_PATH)
        _init_schema(_conn)
    return _conn


def _init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wtp_process (
            time        TIMESTAMPTZ NOT NULL,
            type        VARCHAR,
            instance    VARCHAR,
            attribute   VARCHAR,
            value       DOUBLE
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wtp_fault_events (
            time     TIMESTAMPTZ NOT NULL,
            target   VARCHAR,
            mode     VARCHAR
        )
    """)


def _sync_from_influxdb() -> None:
    """Pull last 90 days from InfluxDB into DuckDB. Replaces the rolling window."""
    client = InfluxDBClient(url=_INFLUXDB_URL, token=_INFLUXDB_TOKEN, org=_INFLUXDB_ORG)
    try:
        conn = get_conn()
        flux = f"""
from(bucket: "{_INFLUXDB_BUCKET}")
  |> range(start: -90d)
  |> filter(fn: (r) => r._measurement == "wtp_process")
  |> pivot(rowKey:["_time","type","instance"], columnKey: ["attribute"], valueColumn: "_value")
"""
        tables = client.query_api().query(flux)
        rows = []
        for table in tables:
            for record in table.records:
                for attr, val in record.values.items():
                    if attr.startswith("_") or not isinstance(val, (int, float)):
                        continue
                    rows.append((
                        record.get_time(),
                        record.values.get("type"),
                        record.values.get("instance"),
                        attr,
                        float(val),
                    ))
        if rows:
            conn.execute("DELETE FROM wtp_process WHERE time > NOW() - INTERVAL '90 days'")
            conn.executemany("INSERT INTO wtp_process VALUES (?, ?, ?, ?, ?)", rows)
        print(f"[analytical] sync complete: {len(rows)} rows")
    finally:
        client.close()


async def sync_loop() -> None:
    """Background task — sync InfluxDB → DuckDB on configured interval."""
    while True:
        try:
            await asyncio.to_thread(_sync_from_influxdb)
        except Exception as exc:
            print(f"[analytical] sync error (will retry in {_SYNC_INTERVAL}s): {exc}")
        await asyncio.sleep(_SYNC_INTERVAL)


def run_correlation(sql: str) -> list[dict]:
    """Read-only analytical query against DuckDB. SELECT only."""
    if not sql.strip().upper().startswith("SELECT"):
        raise ValueError("run_correlation accepts SELECT queries only.")
    conn   = get_conn()
    result = conn.execute(sql).fetchdf()
    return result.to_dict(orient="records")
