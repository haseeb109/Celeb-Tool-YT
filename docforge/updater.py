"""One-click update: git pull + dependency sync. Used by GUI button and start.sh."""
import os
import shutil
import subprocess
import sys
import threading
import time

from .config import ROOT


def _run(cmd):
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def update():
    log = []
    code, out = _run(["git", "rev-parse", "HEAD"])
    before = out if code == 0 else ""
    code, out = _run(["git", "pull", "--ff-only"])
    log.append("$ git pull\n" + out)
    if code != 0:
        log.append("✖ Update fail. Agar aapne tool ki files khud edit ki hain to wo conflict kar rahi hain.")
        return False, "\n".join(log)
    _, after = _run(["git", "rev-parse", "HEAD"])
    if before == after:
        log.append("✔ Tool pehle se latest hai.")
        return False, "\n".join(log)
    _, changed = _run(["git", "diff", "--name-only", before, after])
    log.append("Changed:\n" + changed)
    if "requirements.txt" in changed:
        uv = shutil.which("uv") or "/opt/homebrew/bin/uv"
        code, out = _run([uv, "pip", "install", "--python", sys.executable, "-r", "requirements.txt"])
        log.append("$ uv pip install -r requirements.txt\n" + out[-1500:])
    log.append("✔ Update ho gaya. Tool restart ho raha hai…")
    return True, "\n".join(log)


def restart_soon(delay=2.0):
    def go():
        time.sleep(delay)
        os.execv(sys.executable, [sys.executable, str(ROOT / "app.py")])
    threading.Thread(target=go, daemon=True).start()
