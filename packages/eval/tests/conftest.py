import sys
from pathlib import Path

# Reuse the API test fixtures that build a real recorded project history.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "apps" / "api" / "tests"))

from test_adapt import setup  # noqa: E402, F401  (pytest fixture)
