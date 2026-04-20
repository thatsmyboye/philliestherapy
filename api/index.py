import sys
from pathlib import Path

# Add the web app package root to sys.path so `from app.xxx import ...` resolves.
# app/main.py then adds projects/phillies-bot/ for bot utilities.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "projects" / "sequence-web"))

from app.main import app  # noqa: F401 — re-exported for Vercel ASGI detection
