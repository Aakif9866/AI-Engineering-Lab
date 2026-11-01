"""Settings read from environment (and the repo-root .env). Secrets never leave this module except as headers."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]          # repo root
BACKEND = ROOT / "backend"
DATA = BACKEND / "data"                              # committed fixtures


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def flag(name: str, default: bool = False) -> bool:
    return env(name, "1" if default else "0").lower() in ("1", "true", "yes")


def public() -> bool:
    """Public deploy: never spend the server owner's .env keys and never store visitors' prompt text."""
    return flag("LAB_PUBLIC", bool(env("VERCEL")))


def offline() -> bool:
    return flag("LAB_OFFLINE")


def var_dir(*parts: str) -> Path:
    """Runtime state (db, artifacts, results). LAB_VAR_DIR is read per call so tests can isolate it."""
    # ponytail: on Vercel only /tmp is writable and it is wiped between cold starts; mount a real disk elsewhere if state must persist
    default = "/tmp/lab" if env("VERCEL") else str(BACKEND / "var")
    p = Path(env("LAB_VAR_DIR", default)).joinpath(*parts)
    p.mkdir(parents=True, exist_ok=True)
    return p
