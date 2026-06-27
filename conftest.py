"""
conftest.py — pytest root configuration for the Reindeer/Comet project.

Adds the repo root to sys.path so that `import app.*` works from any test file.
No side effects at import.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the repo root is on sys.path so `import app.*` works
_repo_root = Path(__file__).resolve().parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))
