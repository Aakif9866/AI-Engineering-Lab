"""Long-running work (training, model evaluation) runs as a separate process so the API stays
responsive and GPU/MPS memory is released when the job ends. One job per name at a time."""
import json
import os
import subprocess
import sys
import time

from .config import BACKEND, var_dir


def _meta(name: str):
    return var_dir("jobs") / f"{name}.json"


def running(name: str) -> dict | None:
    p = _meta(name)
    if not p.exists():
        return None
    m = json.loads(p.read_text())
    try:
        os.kill(m["pid"], 0)
    except OSError:
        return None
    # A pid can be reused; treat it as ours only if the process has not outlived a day.
    return m if time.time() - m["started"] < 86400 else None


def spawn(name: str, module: str, args: list[str]) -> dict:
    if running(name):
        raise RuntimeError(f"job '{name}' is already running")
    log = var_dir("jobs") / f"{name}.log"
    proc = subprocess.Popen([sys.executable, "-m", module, *args], cwd=str(BACKEND),
                            stdout=open(log, "w"), stderr=subprocess.STDOUT, start_new_session=True)
    m = {"name": name, "pid": proc.pid, "module": module, "args": args, "started": time.time(), "log": str(log)}
    _meta(name).write_text(json.dumps(m))
    return m


def tail(name: str, n: int = 20) -> str:
    log = var_dir("jobs") / f"{name}.log"
    if not log.exists():
        return ""
    lines = [l for l in log.read_text(errors="replace").splitlines() if "Warning" not in l and "NOTE:" not in l]
    return "\n".join(lines[-n:])
