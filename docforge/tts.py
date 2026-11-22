"""AI33 Pro voiceover (api.ai33.pro). Voices list + search + preview, task-based synthesis, paid-call cache."""
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

import requests

AI33 = "https://api.ai33.pro"
_VOICE_CACHE = {}


def _key():
    k = (os.environ.get("AI33_API_KEY") or "").strip()
    if not k:
        raise RuntimeError("AI33_API_KEY save nahi hai (GUI → 🔑 API Keys)")
    return k


def _h():
    return {"xi-api-key": _key(), "Content-Type": "application/json"}


PROVIDERS = ["elevenlabs", "minimax", "edge", "kokoro", "vbee", "fishaudio", "clone"]
CACHE = None  # set lazily: <root>/.cache/ai33_voices.json


def _cache_path():
    from .config import ROOT
    p = ROOT / ".cache" / "ai33_voices.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _norm(v, prov):
    vid = v.get("voice_id") or v.get("id")
    labels = v.get("labels") or {}
    tags = v.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    return {"name": v.get("name") or v.get("voice_name") or vid, "id": vid,
            "source": v.get("provider") or prov or (vid.split("_")[0] if "_" in str(vid) else ""),
            "gender": (v.get("gender") or labels.get("gender") or "").lower(),
            "accent": v.get("accent") or labels.get("accent") or "",
            "language": v.get("language") or v.get("locale") or labels.get("language") or "",
            "age": v.get("age") or labels.get("age") or "",
            "use_case": v.get("use_case") or labels.get("use_case") or labels.get("description") or "",
            "description": (v.get("description") or "")[:300],
            "tags": [str(t) for t in tags][:8],
            "preview": v.get("preview_url") or v.get("sample_url") or v.get("preview") or ""}


def _fetch_provider(prov, search=""):
    """Saare pages (page_size 100) jab tak has_more."""
    out, page = [], 1
    while page <= 60:
        params = {"provider": prov, "page": page, "page_size": 100}
        if search:
            params["search"] = search
        r = requests.get(f"{AI33}/v3/voices", headers=_h(), params=params, timeout=60)
        if r.status_code != 200:
            if page == 1:
                raise RuntimeError(f"{prov}: {r.status_code} {r.text[:150]}")
            break
        j = r.json()
        items = j.get("data") or j.get("voices") or j.get("items") or (j if isinstance(j, list) else [])
        if isinstance(items, dict):
            items = items.get("voices") or items.get("items") or []
        out += [_norm(v, prov) for v in items if (v.get("voice_id") or v.get("id"))]
        pg = j.get("pagination") or {}
        if not pg.get("has_more") or not items:
            break
        page += 1
    return out


def all_voices(refresh=False, providers=None, log=None):
    """Har provider ki saari voices (cache: 12 ghante). Fail hone wale provider skip."""
    import time as _t
    cp = _cache_path()
    if not refresh and cp.exists() and _t.time() - cp.stat().st_mtime < 12 * 3600:
        vs = json.loads(cp.read_text())
    else:
        vs, errs = [], []
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as ex:
            res = list(ex.map(lambda p: (p, _safe(_fetch_provider, p)), providers or PROVIDERS))
        for p, r in res:
            if isinstance(r, Exception):
                errs.append(f"{p}: {str(r)[:80]}")
            else:
                vs += r
        if not vs and errs:
            raise RuntimeError("AI33 voices nahi aayin — " + "; ".join(errs))
        seen, uniq = set(), []
        for v in vs:
            if v["id"] not in seen:
                seen.add(v["id"])
                uniq.append(v)
        vs = uniq
        cp.write_text(json.dumps(vs))
    for v in vs:
        _VOICE_CACHE[v["id"]] = v
    return vs


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as e:
        return e


def list_voices(search="", source=""):
    """Compat: search across all cached voices (name/description/tags/language)."""
    vs = all_voices()
    q = (search or "").lower().strip()
    out = []
    for v in vs:
        if source and source != "all" and v["source"] != source:
            continue
        if q and q not in " ".join([v["name"], v["description"], v["language"], v["accent"], v["use_case"], " ".join(v["tags"])]).lower():
            continue
        out.append(v)
    return out


def label(v):
    extra = " · ".join(x for x in (v["gender"], v["accent"], v["source"]) if x)
    return f"{v['name']}" + (f"  ({extra})" if extra else "") + f"  ::  {v['id']}"


def preview_url(voice_id):
    return (_VOICE_CACHE.get(voice_id) or {}).get("preview", "")


def resolve_voice(name_or_id):
    s = (name_or_id or "").strip()
    if "::" in s:
        s = s.split("::")[-1].strip()
    if not s:
        raise RuntimeError("Voice select nahi hui")
    try:
        vs = list_voices()
    except Exception:
        return s  # list nahi aayi → jo diya wahi voice_id
    for v in vs:
        if s == v["id"] or s.lower() == v["name"].lower():
            return v["id"]
    for v in vs:
        if s.lower() in v["name"].lower():
            return v["id"]
    return s  # library ki koi voice_id jo pehle page mein nahi


def synth(text, voice_id, vcfg, out_mp3: Path, prev_text="", next_text="", cache_dir: Path = None):
    """Create task → poll /v1/task/{id} → download metadata.audio_url. Returns alignment for subtitles."""
    form = {"text": text, "voice_id": voice_id, "speed": str(float(vcfg.get("speed", 1.0))), "with_transcript": "false"}
    h = hashlib.sha256(json.dumps(["ai33v3", form], sort_keys=True).encode()).hexdigest()[:20]
    cm = None
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cm = cache_dir / f"{h}.mp3"
        if cm.exists():
            out_mp3.write_bytes(cm.read_bytes())
            return _even_alignment(text, out_mp3)
    # AI33 API v3: multipart form (text, voice_id, speed) → task_id
    r = requests.post(f"{AI33}/v3/text-to-speech", headers={"xi-api-key": _key()}, data=form, timeout=120)
    try:
        j = r.json()
    except ValueError:
        raise RuntimeError(f"AI33 {r.status_code}: {r.text[:300]}")
    tid = j.get("task_id") or (j.get("data") or {}).get("task_id")
    if r.status_code >= 300 or j.get("success") is False or not tid:
        raise RuntimeError(f"AI33 task nahi bana ({r.status_code}): {str(j)[:300]}")
    t0, url = time.time(), None
    while True:
        if time.time() - t0 > 600:
            raise RuntimeError(f"AI33 task {tid} 10 min mein complete nahi hua")
        time.sleep(2)
        tj = requests.get(f"{AI33}/v1/task/{tid}", headers={"xi-api-key": _key()}, timeout=60).json()
        st = str(tj.get("status", "")).lower()
        if st == "done":
            md = tj.get("metadata") or {}
            url = md.get("audio_url") or md.get("output_uri") or tj.get("output_uri")
            if not url:
                raise RuntimeError(f"AI33 task done lekin audio URL nahi: {str(tj)[:300]}")
            break
        if st in ("error", "failed"):
            raise RuntimeError(f"AI33 task error: {str(tj.get('error') or tj.get('message') or tj)[:300]}")
    a = requests.get(url, timeout=300)
    a.raise_for_status()
    out_mp3.write_bytes(a.content)
    if cm:
        cm.write_bytes(a.content)
    return _even_alignment(text, out_mp3)


def _even_alignment(text, mp3):
    """AI33 per-character timing nahi deta → subtitles ke liye characters audio length par barabar."""
    d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp3)],
                             capture_output=True, text=True).stdout.strip() or 0)
    n = max(1, len(text))
    return {"characters": list(text), "starts": [d * i / n for i in range(n)], "ends": [d * (i + 1) / n for i in range(n)]}


def words_from_alignment(align):
    out, cur, st, last = [], "", None, 0
    for ch, s, e in zip(align["characters"], align["starts"], align["ends"]):
        if ch.isspace():
            if cur:
                out.append((cur, st, last))
            cur, st = "", None
        else:
            if not cur:
                st = s
            cur += ch
            last = e
    if cur:
        out.append((cur, st, last))
    return out
