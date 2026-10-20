"""One SQLite file for all modules; each module owns its tables and creates them on first use."""
import json
import sqlite3
from contextlib import contextmanager

from .config import var_dir


def db_path() -> str:
    return str(var_dir() / "lab.db")


@contextmanager
def db():
    c = sqlite3.connect(db_path(), timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


_initialised: set[tuple[str, str]] = set()


def ensure(schema: str) -> None:
    """Run a module's CREATE TABLE IF NOT EXISTS script once per process per db file."""
    key = (db_path(), schema)
    if key in _initialised:
        return
    with db() as c:
        c.executescript(schema)
    _initialised.add(key)


def rows(cur) -> list[dict]:
    out = []
    for r in cur.fetchall():
        d = dict(r)
        for k, v in d.items():
            if isinstance(v, str) and k.endswith("_json"):
                d[k] = json.loads(v)
        out.append(d)
    return out
