"""Churn research utilities."""
import os
from pathlib import Path

# Keep matplotlib's cache inside the authorized workspace.
os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parents[1] / "reports" / ".matplotlib"))
