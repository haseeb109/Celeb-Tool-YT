"""ElevenLabs voiceover with per-character timings (for subtitles) and a paid-call cache."""
import base64
import hashlib
import json
import os
from pathlib import Path

import requests

import subprocess
import time

API = "https://api.elevenlabs.io/v1"
AI33 = "https://api.ai33.pro"
PROVIDER = {"name": None}  # set by pipeline/app from config


def effective_provider(cfg):
    """Setting ke mutabiq provider — lekin agar us ki key nahi aur doosre ki hai, to doosra."""
    want = cfg["voice"].get("provider", "elevenlabs")
    has = {"elevenlabs": bool(os.environ.get("ELEVENLABS_API_KEY")), "ai33": bool(os.environ.get("AI33_API_KEY"))}
    if not has.get(want):
        other = "ai33" if want == "elevenlabs" else "elevenlabs"
        if has[other]:
            return other
    return want


def provider():
    if PROVIDER["name"]:
        return PROVIDER["name"]
    from .config import load_config
    return effective_provider(load_config())


def _key(p=None):
    p = p or provider()
    env = "AI33_API_KEY" if p == "ai33" else "ELEVENLABS_API_KEY"
    k = os.environ.get(env)
    if not k:
        raise RuntimeError(f"{env} .env mein nahi mili (GUI → API Keys)")
    return k


def list_voices(p=None):
    """[(name, voice_id, category)] for the active provider."""
    p = p or provider()
    if p == "ai33":
        return _ai33_voices()
    r = requests.get(f"{API}/voices", headers={"xi-api-key": _key(p)}, timeout=60)
    r.raise_for_status()
    return [(v["name"], v["voice_id"], v.get("category", "")) for v in r.json().get("voices", [])]


def _ai33_voices():
    out, seen = [], set()
    for params in ({"page_size": 100}, {"provider": "elevenlabs", "page_size": 100}):
        try:
            r = requests.get(f"{AI33}/v3/voices", headers={"xi-api-key": _key("ai33")}, params=params, timeout=60)
            r.raise_for_status()
            j = r.json()
        except Exception:
            continue
        items = j.get("voices") or j.get("data") or j.get("items") or (j if isinstance(j, list) else [])
        if isinstance(items, dict):
            items = items.get("voices") or items.get("items") or []
        for v in items:
            vid = v.get("voice_id") or v.get("id")
            if vid and vid not in seen:
                seen.add(vid)
                out.append((v.get("name") or v.get("voice_name") or vid, vid, v.get("provider") or v.get("category", "")))
    if not out:
        raise RuntimeError("AI33 se voices list nahi aayi — voice_id seedha paste kar do (ai33.pro dashboard se)")
    return out


def resolve_voice(name_or_id):
    if not name_or_id:
        raise RuntimeError("Voice select nahi hui. config.yaml → voice.voice ya UI se select karo.")
    try:
        voices = list_voices()
    except Exception:
        if " " not in name_or_id.strip():  # list nahi aayi, lekin ye voice_id lagta hai → seedha use karo
            return name_or_id.strip()
        raise
    for name, vid, _ in voices:
        if name_or_id == vid:
            return vid
    for name, vid, _ in voices:
        if name.strip().lower() == name_or_id.strip().lower():
            return vid
    for name, vid, _ in voices:
        if name_or_id.strip().lower() in name.lower():
            return vid
    if len(name_or_id) >= 18 and " " not in name_or_id:  # looks like a raw voice_id from the library
        return name_or_id
    raise RuntimeError(f"Voice '{name_or_id}' account mein nahi mili. Available: {[v[0] for v in voices]}")


def synth(text, voice_id, vcfg, out_mp3: Path, prev_text="", next_text="", cache_dir: Path = None):
    """Returns alignment dict {characters, starts, ends}. Cached by content hash."""
    if provider() == "ai33":
        return _ai33_synth(text, voice_id, vcfg, out_mp3, cache_dir)
    payload = {
        "text": text,
        "model_id": vcfg["model_id"],
        "voice_settings": {"stability": vcfg["stability"], "similarity_boost": vcfg["similarity_boost"],
                           "style": vcfg["style"], "use_speaker_boost": True, "speed": vcfg.get("speed", 1.0)},
        "previous_text": prev_text[-400:] or None,
        "next_text": next_text[:400] or None,
    }
    h = hashlib.sha256(json.dumps([payload, voice_id], sort_keys=True).encode()).hexdigest()[:20]
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cm, ca = cache_dir / f"{h}.mp3", cache_dir / f"{h}.json"
        if cm.exists() and ca.exists():
            out_mp3.write_bytes(cm.read_bytes())
            return json.loads(ca.read_text())
    r = requests.post(f"{API}/text-to-speech/{voice_id}/with-timestamps?output_format=mp3_44100_192",
                      headers={"xi-api-key": _key(), "Content-Type": "application/json"},
                      json=payload, timeout=300)
    if r.status_code != 200:
        raise RuntimeError(f"ElevenLabs {r.status_code}: {r.text[:300]}")
    j = r.json()
    audio = base64.b64decode(j["audio_base64"])
    al = j.get("alignment") or {}
    align = {"characters": al.get("characters", []), "starts": al.get("character_start_times_seconds", []),
             "ends": al.get("character_end_times_seconds", [])}
    out_mp3.write_bytes(audio)
    if cache_dir:
        cm.write_bytes(audio)
        ca.write_text(json.dumps(align))
    return align


def words_from_alignment(align):
    """chars → [(word, start, end)]"""
    out, cur, st = [], "", None
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


def _ai33_synth(text, voice_id, vcfg, out_mp3: Path, cache_dir: Path = None):
    """AI33 Pro: create task → poll /v1/task/{id} → download metadata.audio_url (ElevenLabs-format body)."""
    payload = {"text": text, "model_id": vcfg["model_id"], "with_transcript": False,
               "voice_settings": {"speed": float(vcfg.get("speed", 1.0)), "stability": vcfg["stability"],
                                  "similarity_boost": vcfg["similarity_boost"], "style": vcfg["style"]}}
    h = hashlib.sha256(json.dumps(["ai33", payload, voice_id], sort_keys=True).encode()).hexdigest()[:20]
    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cm = cache_dir / f"{h}.mp3"
        if cm.exists():
            out_mp3.write_bytes(cm.read_bytes())
            return _even_alignment(text, out_mp3)
    hd = {"xi-api-key": _key("ai33"), "Content-Type": "application/json"}
    r = requests.post(f"{AI33}/v1/text-to-speech/{voice_id}?output_format=mp3_44100_192", headers=hd, json=payload, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"AI33 {r.status_code}: {r.text[:300]}")
    j = r.json()
    tid = j.get("task_id")
    if not j.get("success", True) or not tid:
        raise RuntimeError(f"AI33 task nahi bana: {str(j)[:300]}")
    t0 = time.time()
    while True:
        if time.time() - t0 > 600:
            raise RuntimeError(f"AI33 task {tid} 10 min mein complete nahi hua")
        time.sleep(2)
        tj = requests.get(f"{AI33}/v1/task/{tid}", headers=hd, timeout=60).json()
        st = str(tj.get("status", "")).lower()
        if st == "done":
            url = (tj.get("metadata") or {}).get("audio_url")
            break
        if st in ("error", "failed"):
            raise RuntimeError(f"AI33 task error: {str(tj)[:300]}")
    a = requests.get(url, timeout=300)
    a.raise_for_status()
    out_mp3.write_bytes(a.content)
    if cache_dir:
        cm.write_bytes(a.content)
    return _even_alignment(text, out_mp3)


def _even_alignment(text, mp3):
    """AI33 per-character timings nahi deta → subtitles ke liye characters ko audio length par barabar baant do."""
    d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp3)],
                             capture_output=True, text=True).stdout.strip() or 0)
    n = max(1, len(text))
    return {"characters": list(text), "starts": [d * i / n for i in range(n)], "ends": [d * (i + 1) / n for i in range(n)]}
