"""Vercel entrypoint: exposes the FastAPI app from backend/ as one serverless function."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from lab.api import app  # noqa: E402,F401
