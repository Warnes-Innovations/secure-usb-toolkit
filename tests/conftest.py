import sys
from pathlib import Path

# Allow importing tui from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).parent.parent))
