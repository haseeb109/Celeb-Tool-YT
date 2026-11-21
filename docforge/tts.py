"""ElevenLabs voiceover with per-character timings (for subtitles) and a paid-call cache."""
import base64
import hashlib
import json
import os
from pathlib import Path

import requests

API = "https://api.elevenlabs.io/v1"


def _key():
    k = os.environ.get("ELEVENLABS_API_KEY")
    if not k:
        raise RuntimeError("ELEVENLABS_API_KEY .env mein nahi mili")
    return k


def list_voices():
    """Aapke account ki saari voices (cloned + library mein added)."""
    r = requests.get(f"{API}/voices", headers={"xi-api-key": _key()}, timeout=60)
    r.raise_for_status()
    return [(v["name"], v["voice_id"], v.get("category", "")) for v in r.json().get("voices", [])]


def resolve_voice(name_or_id):
    if not name_or_id:
        raise RuntimeError("Voice select nahi hui. config.yaml → voice.voice ya UI se select karo.")
    voices = list_voices()
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
