"""The per-service topology.py shims stay identical (gh-29).

simulator/, chat-ui/ and memory-mcp/ each run as their own process with
their own sys.path, so each carries a 12-line shim that loads the shared
root topology.py. They are copies on purpose; this fails if one drifts.
"""

from pathlib import Path

ROOT = Path(__file__).parent.parent
SHIMS = ["simulator/topology.py", "chat-ui/topology.py", "memory-mcp/topology.py"]


def test_shims_are_identical():
    texts = {path: (ROOT / path).read_text() for path in SHIMS}
    reference = texts[SHIMS[0]]
    drifted = [path for path, text in texts.items() if text != reference]
    assert drifted == [], f"{drifted} differ from {SHIMS[0]}"


def test_shims_delegate_to_the_root_loader():
    for path in SHIMS:
        text = (ROOT / path).read_text()
        assert 'Path(__file__).parent.parent / "topology.py"' in text, path
