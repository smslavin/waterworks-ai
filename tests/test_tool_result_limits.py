"""The enterprise orchestrator caps tool results like the plant loops (gh-24).

It runs in its own process and can't import chat-ui/tool_dispatch.py, so the
value is a copy; this keeps the copy honest. It was 4,000 against 8,000.
"""

import ast
from pathlib import Path

import tool_dispatch

ROOT = Path(__file__).parent.parent


def test_enterprise_cap_matches_the_plant_loops():
    tree = ast.parse((ROOT / "enterprise/orchestrator/enterprise_loop.py").read_text())
    value = next(
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and getattr(node.targets[0], "id", None) == "TOOL_RESULT_MAX_CHARS"
    )
    assert value == tool_dispatch.TOOL_RESULT_MAX_CHARS == 8_000
