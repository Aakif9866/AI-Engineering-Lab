import os
from pathlib import Path


def _load_env(path: Path = Path(__file__).parent / ".env") -> None:
    """Tiny .env reader: KEY=value lines into os.environ, real environment wins."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


_load_env()

PROVIDERS = {
    "deepseek": {
        "url": "https://api.deepseek.com/chat/completions",
        "key": "DEEPSEEK_API_KEY",
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "key": "GROQ_API_KEY",
        "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    },
}
DEFAULT_PROVIDER = os.getenv("LAB_DEFAULT_PROVIDER", "deepseek")
