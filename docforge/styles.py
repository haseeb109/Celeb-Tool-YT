"""Style presets: analyze a reference competitor video once → save → lock for every job."""
import json
import re
import shutil
import time
from pathlib import Path

from . import media, style
from .config import ROOT, load_config, save_local

DIR = ROOT / "styles"


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "style"


def analyze_reference(sources, name, log=print):
    """sources: list of YouTube links and/or local video paths (1–3 videos of the SAME competitor)."""
    cfg = load_config()
    slug = _slug(name)
    ref = DIR / "_ref" / slug
    ref.mkdir(parents=True, exist_ok=True)
    vids = []
    for i, s in enumerate(sources, 1):
        s = s.strip()
        if not s:
            continue
        if s.startswith("http"):
            out = ref / f"ref{i}.mp4"
            media.download(s, out, "1080p", log)
            vids.append(out)
        else:
            p = Path(s)
            dst = ref / f"ref{i}{p.suffix or '.mp4'}"
            if p.resolve() != dst.resolve():
                shutil.copy(p, dst)
            vids.append(dst)
    if not vids:
        raise RuntimeError("Koi link ya video nahi di")
    prof = style.analyze(vids, ref / "work", cfg["video"].get("vision_model") or None, log)
    prof["_meta"] = {"name": name, "sources": [s for s in sources if s.strip()],
                     "created": time.strftime("%Y-%m-%d %H:%M")}
    DIR.mkdir(exist_ok=True)
    (DIR / f"{slug}.json").write_text(json.dumps(prof, indent=2))
    log(f"✔ Style '{name}' save: styles/{slug}.json")
    return slug, prof


def list_styles():
    DIR.mkdir(exist_ok=True)
    return sorted(p.stem for p in DIR.glob("*.json"))


def load(slug):
    p = DIR / f"{slug}.json"
    return json.loads(p.read_text()) if p.exists() else None


def lock(slug):
    if slug and not (DIR / f"{slug}.json").exists():
        raise RuntimeError(f"Style '{slug}' nahi mila")
    save_local({"video": {"style_lock": slug or ""}})


def locked():
    s = load_config()["video"].get("style_lock") or ""
    return s if s and (DIR / f"{s}.json").exists() else ""


def summary(prof):
    if not prof:
        return ""
    p, m, t = prof["pacing"], prof["motion"], prof["transitions"]
    tx = prof.get("text") or {}
    sfx = prof.get("sfx") or {}
    lines = [
        f"**Pacing:** shot {p['median_shot_s']:.1f}s median · {p['cuts_per_min']:.0f} cuts/min",
        f"**Zoom/pan:** {m['moving_ratio']:.0%} shots mein motion · zoom-in {m['zoom_in_ratio']:.0%} · speed {m['zoom_speed'] * 100:.1f}%/s",
        "**Transitions:** " + ", ".join(f"{k} {v:.0%}" for k, v in t.items() if v),
        (f"**Text:** {tx.get('overlay_rate', 0):.0%} shots · {tx.get('position')} · color {tx.get('color_rgb')} · "
         f"{'CAPS' if tx.get('caps_ratio', 0) > 0.6 else 'normal case'}") if tx else "**Text:** detect nahi hua",
        f"**Look:** letterbox {prof['look'].get('letterbox', 0):.0%} · vignette {'haan' if prof['look'].get('vignette_ratio', 1) < 0.72 else 'nahi'} · grain {prof['look'].get('grain', 0):.1f}",
        "**Sound effects (per cut):** " + (", ".join(f"{k} {v:.0%}" for k, v in sfx.items()) or "—"),
    ]
    for n in prof.get("vision") or []:
        if n.get("effects"):
            lines.append("**Effects (vision model):** " + ", ".join(map(str, n["effects"])))
        if n.get("mood"):
            lines.append(f"**Mood:** {n['mood']}")
    return "\n\n".join(lines)
