"""Vercel entrypoint: the FastAPI app from backend/, core deps only (no torch)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
os.environ.setdefault("LAB_VAR_DIR", "/tmp/lab")   # ponytail: /tmp is ephemeral per instance; use a real DB if state must persist
os.environ.setdefault("LAB_EMBEDDER", "hash")      # sentence-transformers/torch exceed the function size budget

from lab.api import app  # noqa: E402,F401
