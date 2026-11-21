"""Sound-effects: default library (synthesized once with FFmpeg, free) + timeline renderer.
Apne SFX use karne hon to assets/sfx/whoosh|hit|riser/ folders mein wav/mp3 daal do — wo pehle use honge."""
import random
import subprocess
import wave
from pathlib import Path

import numpy as np

SR = 48000
RECIPES = {  # name: ffmpeg lavfi source + filters
    "whoosh/whoosh_1.wav": "anoisesrc=d=0.7:c=pink:a=0.6,highpass=f=400,lowpass=f=6000,afade=t=in:d=0.35,afade=t=out:st=0.35:d=0.35",
    "whoosh/whoosh_2.wav": "anoisesrc=d=0.5:c=white:a=0.4,bandpass=f=2500:w=3000,afade=t=in:d=0.2,afade=t=out:st=0.2:d=0.3",
    "hit/hit_1.wav": "sine=f=55:d=1.2,volume=2.5,afade=t=out:st=0.05:d=1.1",
    "hit/hit_2.wav": "sine=f=42:d=1.6,volume=2.8,afade=t=out:st=0.03:d=1.5",
    "riser/riser_1.wav": "anoisesrc=d=1.6:c=pink:a=0.5,highpass=f=300,afade=t=in:d=1.5:curve=exp,afade=t=out:st=1.5:d=0.1",
}


def ensure_library(root: Path):
    for rel, src in RECIPES.items():
        p = root / rel
        if p.exists():
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", src, "-ac", "2", "-ar", str(SR), str(p)], check=True)


def _load(path: Path, cache={}):
    if path not in cache:
        tmp = path.with_suffix(".48k.raw")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "2", "-ar", str(SR), str(tmp)], check=True)
        cache[path] = np.frombuffer(tmp.read_bytes(), dtype=np.int16).astype(np.float32).reshape(-1, 2) / 32768
        tmp.unlink()
    return cache[path]


def render(events, total, root: Path, out: Path, seed, gain_db=-6):
    """events: [(time_s, kind)] kind in whoosh/hit/riser. Riser ends exactly at its time."""
    ensure_library(root)
    rng = random.Random(seed)
    files = {k: sorted(p for p in (root / k).glob("*") if p.suffix.lower() in (".wav", ".mp3", ".aiff", ".m4a"))
             for k in ("whoosh", "hit", "riser")}
    buf = np.zeros((int((total + 2) * SR), 2), np.float32)
    g = 10 ** (gain_db / 20)
    for t, kind in events:
        if not files.get(kind):
            continue
        a = _load(rng.choice(files[kind]))
        start = int((t - (len(a) / SR if kind == "riser" else 0.12 if kind == "whoosh" else 0)) * SR)
        start = max(0, start)
        end = min(len(buf), start + len(a))
        buf[start:end] += a[:end - start] * g
    buf = np.clip(buf[:int(total * SR)], -1, 1)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((buf * 32767).astype(np.int16).tobytes())
    return out


def plan_events(cuts, clip_starts, rates, seed):
    """cuts: [(t, trans)] b-roll cuts; clip_starts: [t] PLAY CLIP moments. rates from style profile."""
    rng = random.Random(seed)
    ev = []
    w, h, r = rates.get("whoosh", 0), rates.get("hit", 0), rates.get("riser", 0)
    for t, tr in cuts:
        x = rng.random()
        if x < r:
            ev.append((t, "riser"))
        elif x < r + h:
            ev.append((t, "hit"))
        elif x < r + h + w or tr in ("flash", "dip_to_black"):
            ev.append((t, "whoosh"))
    for t in clip_starts:  # competitor-style accent into original clips, at the measured overall SFX rate
        if rng.random() < min(1.0, (w + h + r) * 1.5):
            ev.append((t, "hit" if h >= w else "whoosh"))
    return ev
