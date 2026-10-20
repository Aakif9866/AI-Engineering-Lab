"""Least-privilege SQL: three independent layers, so a bug in one does not open the database.

1. Static validator: one statement, SELECT/WITH only, allow-listed tables, no forbidden keywords,
   sensitive columns blocked per role, LIMIT enforced.
2. Read-only connection: SQLite opened with mode=ro and PRAGMA query_only, so writes fail in the engine.
3. Authorizer callback: SQLite asks us about every table/column read during execution and we deny
   anything outside the role's grant, which catches what the regex validator missed.
"""
import random
import re
import sqlite3

from lab.core.config import var_dir

ALLOWED_TABLES = {"orders", "shipments", "customers"}
SENSITIVE_COLUMNS = {("customers", "email"), ("customers", "phone")}
ROLE_SENSITIVE_OK = {"admin"}
MAX_LIMIT = 100
_FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|replace|vacuum|trigger|reindex|load_extension)\b", re.I)


class SQLRejected(Exception):
    error_type = "sql_rejected"


def db_path() -> str:
    p = var_dir("p04") / "analytics.db"
    if not p.exists():
        _seed(str(p))
    return str(p)


def _seed(path: str) -> None:
    rng = random.Random(4)
    c = sqlite3.connect(path)
    c.executescript("""
      CREATE TABLE customers(id INTEGER PRIMARY KEY, name TEXT, email TEXT, phone TEXT, region TEXT);
      CREATE TABLE orders(id INTEGER PRIMARY KEY, customer_id INTEGER, sku TEXT, qty INTEGER, total_usd REAL, status TEXT, created TEXT);
      CREATE TABLE shipments(id INTEGER PRIMARY KEY, order_id INTEGER, carrier TEXT, status TEXT, eta TEXT);
      CREATE TABLE secrets(name TEXT, value TEXT);""")
    names = ["Acme Clinics", "Bluebird Pharmacy", "Cedar Health", "Delta Labs", "Evergreen Vets", "Fjord Biotech"]
    for i, n in enumerate(names, 1):
        c.execute("INSERT INTO customers VALUES(?,?,?,?,?)", (i, n, f"ops{i}@{n.split()[0].lower()}.example", f"415-555-01{i:02d}", rng.choice(["west", "east", "eu"])))
    for o in range(1, 61):
        c.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?)", (o, rng.randint(1, 6), rng.choice(["VX-88213", "VX-88214", "IN-1102", "AB-3301"]),
                                                               rng.randint(1, 40) * 10, round(rng.uniform(200, 9000), 2),
                                                               rng.choice(["placed", "shipped", "delivered", "delayed"]), f"2026-03-{rng.randint(1, 28):02d}"))
        c.execute("INSERT INTO shipments VALUES(?,?,?,?,?)", (o, o, rng.choice(["FrostLine Freight", "ColdPath", "PolarExpress"]),
                                                              rng.choice(["in_transit", "delivered", "late"]), f"2026-04-{rng.randint(1, 20):02d}"))
    c.execute("INSERT INTO secrets VALUES('payment_api_key','pk_live_FAKE_DO_NOT_LEAK_7731')")
    c.commit()
    c.close()


def strip_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S)


def validate(sql: str, role: str) -> tuple[str, list[str]]:
    """Returns (safe_sql, notes) or raises SQLRejected with the rule that fired."""
    if len(sql) > 2000:
        raise SQLRejected("query too long")
    s = strip_comments(sql).strip().rstrip(";").strip()
    if ";" in s:
        raise SQLRejected("multiple statements are not allowed")
    if not re.match(r"^(select|with)\b", s, re.I):
        raise SQLRejected("only SELECT queries are allowed")
    if m := _FORBIDDEN.search(s):
        raise SQLRejected(f"forbidden keyword: {m.group(1).upper()}")
    tables = {t.lower() for t in re.findall(r"\b(?:from|join)\s+([A-Za-z_][A-Za-z0-9_]*)", s, re.I)}
    ctes = {t.lower() for t in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s+as\s*\(", s, re.I)}
    if bad := (tables - ctes - ALLOWED_TABLES):
        raise SQLRejected(f"table not allowed: {', '.join(sorted(bad))}")
    if role not in ROLE_SENSITIVE_OK:
        for _, col in SENSITIVE_COLUMNS:
            if re.search(rf"\b{col}\b", s, re.I):
                raise SQLRejected(f"column '{col}' is restricted for role {role}")
    notes = []
    m = re.search(r"\blimit\s+(\d+)\s*$", s, re.I)
    if not m:
        s += f" LIMIT {MAX_LIMIT}"
        notes.append(f"LIMIT {MAX_LIMIT} appended")
    elif int(m.group(1)) > MAX_LIMIT:
        s = s[:m.start()] + f"LIMIT {MAX_LIMIT}"
        notes.append(f"LIMIT reduced to {MAX_LIMIT}")
    return s, notes


def execute(sql: str, role: str) -> dict:
    """Validate, then run on a read-only connection with an authorizer that enforces the same grant."""
    safe, notes = validate(sql, role)
    denied: list[str] = []

    def authorizer(action, arg1, arg2, dbname, source):
        if action == sqlite3.SQLITE_READ:
            table, col = (arg1 or "").lower(), (arg2 or "").lower()
            if table not in ALLOWED_TABLES or ((table, col) in SENSITIVE_COLUMNS and role not in ROLE_SENSITIVE_OK):
                denied.append(f"{table}.{col}")
                return sqlite3.SQLITE_DENY
        elif action not in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE):
            denied.append(f"action {action}")
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    con = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True)
    try:
        con.execute("PRAGMA query_only=ON")
        con.set_authorizer(authorizer)
        cur = con.execute(safe)
        cols = [d[0] for d in cur.description]
        data = cur.fetchmany(MAX_LIMIT)
    except sqlite3.DatabaseError as e:
        raise SQLRejected(f"engine refused: {e}" + (f" (authorizer denied {', '.join(denied)})" if denied else "")) from e
    finally:
        con.close()
    return {"sql": safe, "notes": notes, "columns": cols, "rows": data, "row_count": len(data)}
