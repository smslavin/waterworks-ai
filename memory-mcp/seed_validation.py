"""Validates that schema.cypher seeds correctly on an empty LadybugDB.

Run from memory-mcp/:
    .venv/bin/python seed_validation.py

Uses a temp database so the real data/ directory is untouched.
"""

import os
import tempfile

# Point at a throw-away DB so we never touch data/
with tempfile.TemporaryDirectory() as tmp:
    os.environ["LADYBUG_DB_PATH"] = f"{tmp}/test.db"

    import graph

    conn = graph.get_conn()

    # Facility should exist after seed
    facilities = list(conn.execute("MATCH (n:Facility) RETURN n.id AS id, n.name AS name").rows_as_dict())
    print(f"Facilities ({len(facilities)}):", facilities)
    assert len(facilities) == 1, "Expected exactly 1 Facility after seed"

    # Process areas
    areas = list(conn.execute("MATCH (a:ProcessArea) RETURN a.id AS id, a.name AS name").rows_as_dict())
    print(f"ProcessAreas ({len(areas)}):", [r["id"] for r in areas])
    assert len(areas) == 3, "Expected 3 ProcessAreas"

    # Equipment instances
    equipment = list(conn.execute("MATCH (e:Equipment) RETURN e.id AS id").rows_as_dict())
    print(f"Equipment ({len(equipment)}):", [r["id"] for r in equipment])
    assert len(equipment) == 10, "Expected 10 Equipment instances"

    # Tag bindings — check BINDS_ATTRIBUTE relationships exist
    bindings = list(conn.execute("""
        MATCH (e:Equipment)-[:BINDS_ATTRIBUTE]->(b:TagBinding)
        RETURN count(*) AS c
    """).rows_as_dict())
    binding_count = bindings[0]["c"]
    print(f"TagBindings wired: {binding_count}")
    assert binding_count > 0, "Expected tag bindings to be wired"

    # Specialist context for intake area
    rows = graph.get_specialist_context("intake")
    ctx  = graph.aggregate_specialist_query(rows)
    print(f"Intake specialist context: area={ctx.get('area')}, equipment count={len(ctx.get('equipment', []))}")
    assert ctx.get("area") == "Raw Water Intake"

    print("\nAll assertions passed — schema seeded correctly.")
