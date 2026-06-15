import sys
from pathlib import Path

root = Path(__file__).parent.parent
sys.path.insert(0, str(root / "chat-ui"))
sys.path.insert(
    0, str(root / "simulator")
)  # simulator wins on 'topology' name conflict
