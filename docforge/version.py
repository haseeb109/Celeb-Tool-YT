"""Version = v1.<commit count>. Har update (commit) ek naya version."""
import subprocess

from .config import ROOT

LAST = ROOT / ".last_version"


def _git(*a, timeout=20):
    p = subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    return p.stdout.strip() if p.returncode == 0 else ""


def label(n):
    return f"v1.{n}" if n else "v1.0"


def current():
    n = _git("rev-list", "--count", "HEAD")
    d = _git("log", "-1", "--format=%cd", "--date=format:%d %b")
    return {"n": int(n or 0), "label": label(int(n or 0)), "date": d, "sha": _git("rev-parse", "HEAD")}


def remote():
    """git fetch → kitne naye updates aaye hain."""
    try:
        _git("fetch", "--quiet", timeout=15)
    except Exception:
        return None
    n = _git("rev-list", "--count", "@{u}")
    behind = _git("rev-list", "--count", "HEAD..@{u}")
    if not n:
        return None
    return {"n": int(n), "label": label(int(n)), "behind": int(behind or 0)}


def changelog(old_sha, new_sha="HEAD", limit=15):
    out = _git("log", f"{old_sha}..{new_sha}", f"-{limit}", "--format=%s")
    return [l for l in out.splitlines() if l.strip()]


def just_updated():
    """App start par: pichli dafa se version badla? → (old_label, new, changes)."""
    cur = current()
    prev = LAST.read_text().split() if LAST.exists() else []
    LAST.write_text(f"{cur['n']} {cur['sha']}")
    if prev and len(prev) == 2 and prev[1] != cur["sha"]:
        return label(int(prev[0])), cur, changelog(prev[1], cur["sha"])
    return None
