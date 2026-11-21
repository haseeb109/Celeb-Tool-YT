import json
import re
import time
from pathlib import Path

import yaml

from .config import ROOT, load_config


def jobs_dir():
    d = ROOT / load_config()["paths"]["jobs"]
    d.mkdir(exist_ok=True)
    return d


def create_job(name, link1, transcript1, link2, transcript2, rumor, quality=None, voice=None, subtitles=None):
    slug = re.sub(r"[^a-z0-9]+", "-", (name or rumor)[:40].lower()).strip("-") or "job"
    d = jobs_dir() / f"{time.strftime('%m%d-%H%M%S')}-{slug}"
    d.mkdir(parents=True)
    spec = {"link1": link1.strip(), "link2": (link2 or "").strip(), "rumor": rumor.strip()}
    if quality:
        spec["quality"] = quality
    if voice:
        spec["voice"] = voice
    if subtitles is not None:
        spec["subtitles"] = bool(subtitles)
    (d / "job.yaml").write_text(yaml.safe_dump(spec, allow_unicode=True, sort_keys=False))
    (d / "transcript1.txt").write_text(transcript1)
    if transcript2 and transcript2.strip():
        (d / "transcript2.txt").write_text(transcript2)
    return d


def list_jobs():
    rows = []
    for d in sorted(jobs_dir().iterdir()):
        if not (d / "job.yaml").exists() or d.name.startswith("_"):
            continue
        st = json.loads((d / "status.json").read_text()) if (d / "status.json").exists() else {"state": "pending", "done": []}
        rows.append({"job": d.name, "state": st.get("state"), "stages_done": len(st.get("done", [])),
                     "error": (st.get("error") or "")[:120], "path": d})
    return rows
