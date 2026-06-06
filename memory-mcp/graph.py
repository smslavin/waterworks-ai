"""LadybugDB graph layer — topology reads and dynamic layer writes.

Package: pip install ladybug-client  →  import ladybug as lb
Result iteration: list(result.rows_as_dict()) returns list[dict] with column names as keys.
Parameterized queries use $param notation (Kuzu-compatible).
Connection is module-level; threading.Lock guards initialization only.
"""

import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import ladybug as lb

_DB_PATH     = os.environ.get("LADYBUG_DB_PATH", "../data/ladybugdb/fieldworks.db")
_SCHEMA_PATH = Path(__file__).parent.parent / "ladybugdb" / "schema.cypher"

_db:   lb.Database   | None = None
_conn: lb.Connection | None = None
_lock = threading.Lock()


def get_conn() -> lb.Connection:
    global _db, _conn
    with _lock:
        if _conn is None:
            Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
            _db   = lb.Database(_DB_PATH)
            _conn = lb.Connection(_db)
            _maybe_seed(_conn)
    return _conn


def _maybe_seed(conn: lb.Connection) -> None:
    """Seed from schema.cypher if the database is empty."""
    try:
        result = conn.execute("MATCH (n:Facility) RETURN count(n) AS c")
        rows   = list(result.rows_as_dict())
        count  = rows[0]["c"] if rows else 0
    except Exception:
        count = 0
    if count == 0:
        _load_schema(conn)


def _load_schema(conn: lb.Connection) -> None:
    """Execute schema.cypher statement by statement.

    Two quirks in the schema file require pre-processing before splitting on ';':

    1. Inline // comments — some column definitions have trailing comments that
       contain ';' (e.g. "notes STRING // Operational history; persists...").
       Stripping all // comments first removes these spurious semicolons.

    2. Tag-binding lines have TWO CREATE clauses on one line separated by
       ';     ' (semicolon + spaces, no newline). These two CREATEs share the
       preceding MATCH's variable scope and must be submitted as a single
       multi-clause query. Only replace '; CREATE' patterns where there is no
       newline between the ';' and 'CREATE' — i.e. same-line only — so that
       normal statement boundaries (';' at end of line, next statement on the
       following line) are preserved.
    """
    cypher = _SCHEMA_PATH.read_text()

    # 1. Remove all // comments (standalone lines and inline alike).
    cypher = re.sub(r"//[^\n]*", "", cypher)

    # 2. Normalise same-line '; CREATE' to '\nCREATE' (multi-clause, not new
    #    statement). [^\S\n]+ matches horizontal whitespace only, not newlines.
    cypher = re.sub(r";[^\S\n]+CREATE", "\nCREATE", cypher)

    for raw in cypher.split(";"):
        stmt = raw.strip()
        if not stmt:
            continue
        try:
            conn.execute(stmt)
        except Exception as exc:
            # Log and continue — RETURN-only example queries at the bottom of
            # the schema file also pass through here harmlessly.
            print(f"[graph] schema load: {exc!r}")


# ── Read tools ────────────────────────────────────────────────────────────────

def get_topology() -> list[dict]:
    conn = get_conn()
    result = conn.execute("""
        MATCH (area:ProcessArea)-[:CONTAINS_EQUIPMENT]->(e:Equipment)-[:IS_TYPE]->(t:EquipmentType)
        RETURN area.name AS area, area.id AS area_id,
               e.id AS equipment, e.name AS equipment_name, e.notes AS notes,
               t.id AS type_id, t.name AS type_name
        ORDER BY area.name, e.id
    """)
    return list(result.rows_as_dict())


def get_specialist_context(area_id: str) -> list[dict]:
    """Flat rows for aggregate_specialist_query()."""
    conn = get_conn()
    result = conn.execute(f"""
        MATCH (area:ProcessArea {{id: '{area_id}'}})-[:CONTAINS_EQUIPMENT]->(e:Equipment)
              -[:IS_TYPE]->(t:EquipmentType)
        OPTIONAL MATCH (t)-[:DEFINES_ATTRIBUTE]->(attr:Attribute)
        OPTIONAL MATCH (t)-[:HAS_FAULT_MODE]->(fm:FaultMode)
        OPTIONAL MATCH (e)-[:BINDS_ATTRIBUTE {{attribute_id: attr.id}}]->(b:TagBinding)
        RETURN
            area.name AS process_area, area.specialist_prompt AS area_context,
            e.name AS equipment, e.notes AS equipment_notes, t.name AS equipment_type,
            attr.name AS attribute, attr.units AS units,
            attr.normal_range_min AS normal_min, attr.normal_range_max AS normal_max,
            b.tag_id AS tag_id, b.confidence AS binding_confidence,
            fm.name AS fault_mode, fm.severity AS fault_severity,
            fm.description AS fault_description
        ORDER BY e.name, attr.name
    """)
    return list(result.rows_as_dict())


def aggregate_specialist_query(rows: list[dict]) -> dict:
    """Collapse flat join rows into structured specialist context."""
    if not rows:
        return {}
    area_name    = rows[0]["process_area"]
    area_context = rows[0]["area_context"]
    equipment: dict[str, dict] = {}
    for row in rows:
        eq = row["equipment"]
        if eq not in equipment:
            equipment[eq] = {
                "name": eq, "type": row["equipment_type"],
                "notes": row["equipment_notes"],
                "attributes": {}, "fault_modes": {},
            }
        if row["attribute"]:
            equipment[eq]["attributes"][row["attribute"]] = {
                "units": row["units"],
                "normal_min": row["normal_min"], "normal_max": row["normal_max"],
                "tag_id": row["tag_id"], "confidence": row["binding_confidence"],
            }
        if row["fault_mode"] and row["fault_mode"] not in equipment[eq]["fault_modes"]:
            equipment[eq]["fault_modes"][row["fault_mode"]] = {
                "severity": row["fault_severity"],
                "description": row["fault_description"],
            }
    return {"area": area_name, "context": area_context, "equipment": list(equipment.values())}


def get_equipment_history(equipment_id: str, limit: int = 10) -> dict:
    conn = get_conn()

    inc = conn.execute(f"""
        MATCH (i:Incident)-[:INCIDENT_ON]->(e:Equipment {{id: '{equipment_id}'}})
        OPTIONAL MATCH (i)-[:CONSISTENT_WITH]->(fm:FaultMode)
        RETURN i.timestamp AS ts, i.diagnosis AS diagnosis,
               i.status AS status, i.confidence AS confidence,
               i.outcome AS outcome, fm.name AS fault_mode
        ORDER BY i.timestamp DESC LIMIT {limit}
    """)
    incidents = list(inc.rows_as_dict())

    obs = conn.execute(f"""
        MATCH (o:Observation)-[:OBSERVATION_ON]->(e:Equipment {{id: '{equipment_id}'}})
        RETURN o.timestamp AS ts, o.text AS text,
               o.confidence AS confidence, o.specialist AS specialist
        ORDER BY o.timestamp DESC LIMIT {limit}
    """)
    observations = list(obs.rows_as_dict())

    dec = conn.execute(f"""
        MATCH (d:OperatorDecision)-[:DECISION_ON]->(e:Equipment {{id: '{equipment_id}'}})
        RETURN d.action_type AS action_type, d.decision AS decision, count(*) AS count
        ORDER BY count DESC LIMIT 5
    """)
    decisions = list(dec.rows_as_dict())

    return {
        "equipment_id":    equipment_id,
        "incidents":       incidents,
        "observations":    observations,
        "decision_patterns": decisions,
    }


def get_writable_attributes() -> list[dict]:
    conn = get_conn()
    result = conn.execute("""
        MATCH (e:Equipment)-[:BINDS_ATTRIBUTE]->(b:TagBinding)-[:BINDING_OF]->(a:Attribute {writable: true})
        RETURN e.id AS equipment_id, e.name AS equipment_name,
               a.name AS attribute, b.tag_id AS tag_id,
               a.requires_confirmation AS requires_confirmation,
               a.write_limit_min AS write_limit_min,
               a.write_limit_max AS write_limit_max
    """)
    return list(result.rows_as_dict())


def query_graph(cypher: str) -> list[dict]:
    """Read-only escape hatch. Rejects write operations."""
    upper = cypher.strip().upper()
    for kw in ("CREATE", "MERGE", "SET", "DELETE", "DETACH", "DROP"):
        if kw in upper:
            raise ValueError(f"query_graph is read-only. Found '{kw}'. Use record_* tools to write.")
    conn = get_conn()
    return conn.execute(cypher).rows_as_dict()


# ── Write tools ───────────────────────────────────────────────────────────────

def record_incident(
    session_id: str, equipment_id: str, diagnosis: str,
    confidence: float, status: str,
    fault_mode_id: str | None = None,
) -> str:
    conn        = get_conn()
    incident_id = str(uuid.uuid4())[:12]
    ts          = datetime.now(timezone.utc).isoformat()

    # Escape single quotes in diagnosis text
    diagnosis_safe = diagnosis.replace("'", "\\'")

    conn.execute(f"""
        CREATE (:Incident {{
            id: '{incident_id}', session_id: '{session_id}', timestamp: '{ts}',
            diagnosis: '{diagnosis_safe}', confidence: {confidence},
            status: '{status}', outcome: 'monitoring'
        }})
    """)
    conn.execute(f"""
        MATCH (i:Incident {{id: '{incident_id}'}}), (e:Equipment {{id: '{equipment_id}'}})
        CREATE (i)-[:INCIDENT_ON]->(e)
    """)
    if fault_mode_id:
        conn.execute(f"""
            MATCH (i:Incident {{id: '{incident_id}'}}), (fm:FaultMode {{id: '{fault_mode_id}'}})
            CREATE (i)-[:CONSISTENT_WITH]->(fm)
        """)
    return incident_id


def record_observation(
    session_id: str, equipment_id: str, text: str,
    confidence: float, specialist: str,
) -> str:
    conn   = get_conn()
    obs_id = str(uuid.uuid4())[:12]
    ts     = datetime.now(timezone.utc).isoformat()

    text_safe = text.replace("'", "\\'")

    conn.execute(f"""
        CREATE (:Observation {{
            id: '{obs_id}', session_id: '{session_id}', timestamp: '{ts}',
            text: '{text_safe}', confidence: {confidence}, specialist: '{specialist}'
        }})
    """)
    conn.execute(f"""
        MATCH (o:Observation {{id: '{obs_id}'}}), (e:Equipment {{id: '{equipment_id}'}})
        CREATE (o)-[:OBSERVATION_ON]->(e)
    """)
    return obs_id


def link_incident_precedes(incident_a_id: str, incident_b_id: str, hours_apart: float) -> None:
    conn = get_conn()
    conn.execute(f"""
        MATCH (a:Incident {{id: '{incident_a_id}'}}), (b:Incident {{id: '{incident_b_id}'}})
        CREATE (a)-[:PRECEDES {{hours_apart: {hours_apart}}}]->(b)
    """)
