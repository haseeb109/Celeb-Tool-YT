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


def list_voices(search="", source=""):
    """[{name, id, source, gender, accent, preview}] from AI33 /v3/voices.
    AI33 ka API 'provider' lazmi mangta hai — abhi sirf 'elevenlabs' allowed hai."""
    params = {"page_size": 100, "provider": source or "elevenlabs"}
    if search:
        params["search"] = search
    r = requests.get(f"{AI33}/v3/voices", headers=_h(), params=params, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"AI33 voices {r.status_code}: {r.text[:200]}")
    j = r.json()
    items = j.get("voices") or j.get("data") or j.get("items") or (j if isinstance(j, list) else [])
    if isinstance(items, dict):
        items = items.get("voices") or items.get("items") or []
    out = []
    for v in items:
        vid = v.get("voice_id") or v.get("id")
        if not vid:
            continue
        labels = v.get("labels") or {}
        d = {"name": v.get("name") or v.get("voice_name") or vid, "id": vid,
             "source": v.get("provider") or v.get("category") or "",
             "gender": v.get("gender") or labels.get("gender", ""), "accent": v.get("accent") or labels.get("accent", ""),
             "preview": v.get("preview_url") or v.get("sample_url") or v.get("preview") or ""}
        out.append(d)
        _VOICE_CACHE[vid] = d
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
    payload = {"text": text, "model_id": vcfg["model_id"], "with_transcript": False,
               "voice_settings": {"speed": float(vcfg.get("speed", 1.0)), "stability": vcfg["stability"],
                                  "similarity_boost": vcfg["similarity_boost"], "style": vcfg["style"]}}
    h = hashlib.sha256(json.dumps(["ai33", payload, voice_id], sort_keys=True).encode()).hexdigest()[:20]
    cm = None
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cm = cache_dir / f"{h}.mp3"
        if cm.exists():
            out_mp3.write_bytes(cm.read_bytes())
            return _even_alignment(text, out_mp3)
    r = requests.post(f"{AI33}/v1/text-to-speech/{voice_id}?output_format=mp3_44100_192", headers=_h(), json=payload, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"AI33 {r.status_code}: {r.text[:300]}")
    j = r.json()
    tid = j.get("task_id")
    if not j.get("success", True) or not tid:
        raise RuntimeError(f"AI33 task nahi bana: {str(j)[:300]}")
    t0, url = time.time(), None
    while True:
        if time.time() - t0 > 600:
            raise RuntimeError(f"AI33 task {tid} 10 min mein complete nahi hua")
        time.sleep(2)
        tj = requests.get(f"{AI33}/v1/task/{tid}", headers=_h(), timeout=60).json()
        st = str(tj.get("status", "")).lower()
        if st == "done":
            url = (tj.get("metadata") or {}).get("audio_url")
            break
        if st in ("error", "failed"):
            raise RuntimeError(f"AI33 task error: {str(tj)[:300]}")
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
