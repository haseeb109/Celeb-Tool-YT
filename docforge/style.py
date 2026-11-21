"""Competitor editing-style analyzer (100% local, free).

Measures from the two source videos:
  pacing      — PySceneDetect cuts → shot lengths
  motion      — OpenCV feature matching → zoom in/out speed, pan
  transitions — luma around each cut → hard cut / flash / dip-to-black / crossfade
  text        — Apple Vision OCR (ocrmac, Mac) → position, size, color, CAPS, frequency
  look        — letterbox, vignette, grain (pixel stats) + optional local vision model (Ollama Qwen2.5-VL)
  sfx         — audio transients at cuts → whoosh / hit / riser rate
Output: style_profile.json, consumed by the visuals + assemble stages.
"""
import base64
import json
import subprocess
import wave
from pathlib import Path

import cv2
import numpy as np


def _log(log, m):
    (log or print)(m)


# ------------------------------------------------------------------ pacing
def detect_cuts(video):
    from scenedetect import ContentDetector, detect
    scenes = detect(str(video), ContentDetector(threshold=27.0, min_scene_len=8), show_progress=False)
    if not scenes:  # one continuous shot
        cap = cv2.VideoCapture(str(video))
        d = cap.get(cv2.CAP_PROP_FRAME_COUNT) / (cap.get(cv2.CAP_PROP_FPS) or 30)
        return [(0.0, d)]
    return [(s.get_seconds(), e.get_seconds()) for s, e in scenes]


# ------------------------------------------------------------------ motion
def _frame_at(cap, t, w=640):
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, f = cap.read()
    if not ok:
        return None
    h = int(f.shape[0] * w / f.shape[1])
    return cv2.resize(f, (w, h))


def shot_motion(cap, a, b):
    """scale change per second (+ zoom in, − zoom out) and horizontal pan (fraction of width per second)."""
    d = b - a
    if d < 0.8:
        return 0.0, 0.0
    f1, f2 = _frame_at(cap, a + 0.15), _frame_at(cap, b - 0.15)
    if f1 is None or f2 is None:
        return 0.0, 0.0
    orb = cv2.ORB_create(800)
    k1, d1 = orb.detectAndCompute(cv2.cvtColor(f1, cv2.COLOR_BGR2GRAY), None)
    k2, d2 = orb.detectAndCompute(cv2.cvtColor(f2, cv2.COLOR_BGR2GRAY), None)
    if d1 is None or d2 is None or len(k1) < 20 or len(k2) < 20:
        return 0.0, 0.0
    m = sorted(cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d1, d2), key=lambda x: x.distance)[:200]
    if len(m) < 15:
        return 0.0, 0.0
    p1 = np.float32([k1[x.queryIdx].pt for x in m])
    p2 = np.float32([k2[x.trainIdx].pt for x in m])
    A, inl = cv2.estimateAffinePartial2D(p1, p2, method=cv2.RANSAC)
    if A is None or inl.sum() < 12:
        return 0.0, 0.0
    scale = float(np.sqrt(A[0, 0] ** 2 + A[1, 0] ** 2))
    span = (b - a - 0.3)
    return (scale - 1) / span, float(A[0, 2]) / f1.shape[1] / span


# ------------------------------------------------------------------ transitions
def classify_transition(cap, t, fps):
    """Luma profile ±0.4s around a cut."""
    lum, diffs, prev = [], [], None
    for k in range(-12, 13):
        f = _frame_at(cap, max(0, t + k / fps), 320)
        if f is None:
            continue
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)
        lum.append(g.mean())
        if prev is not None:
            diffs.append(np.abs(g - prev).mean())
        prev = g
    if len(lum) < 10:
        return "cut"
    lum = np.array(lum)
    base = np.median(np.r_[lum[:4], lum[-4:]])
    if lum.max() > max(200, base + 60):
        return "flash"
    if lum.min() < min(20, base - 50):
        return "dip_to_black"
    diffs = np.array(diffs)
    if (diffs > diffs.max() * 0.35).sum() >= 6:  # change spread over many frames
        return "crossfade"
    return "cut"


# ------------------------------------------------------------------ look
def look_stats(cap, times):
    sat, lb, vig, grain = [], [], [], []
    for t in times:
        f = _frame_at(cap, t, 640)
        if f is None:
            continue
        hsv = cv2.cvtColor(f, cv2.COLOR_BGR2HSV)
        sat.append(hsv[..., 1].mean())
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY).astype(np.float32)
        h = g.shape[0]
        rows = g.mean(axis=1)
        bar = 0
        while bar < h // 4 and rows[bar] < 12 and rows[h - 1 - bar] < 12:
            bar += 1
        lb.append(bar / h)
        c = g[h // 3:2 * h // 3, g.shape[1] // 3:2 * g.shape[1] // 3].mean() + 1
        corners = np.mean([g[:h // 6, :g.shape[1] // 8].mean(), g[:h // 6, -g.shape[1] // 8:].mean(),
                           g[-h // 6:, :g.shape[1] // 8].mean(), g[-h // 6:, -g.shape[1] // 8:].mean()])
        vig.append(corners / c)
        grain.append(float(np.std(g - cv2.GaussianBlur(g, (5, 5), 0))))
    return {"saturation": float(np.median(sat)) if sat else 0, "letterbox": float(np.median(lb)) if lb else 0,
            "vignette_ratio": float(np.median(vig)) if vig else 1, "grain": float(np.median(grain)) if grain else 0}


# ------------------------------------------------------------------ text (Mac OCR)
def ocr_frame(img_path):
    try:
        from ocrmac import ocrmac
    except Exception:
        return None
    try:
        return ocrmac.OCR(str(img_path), recognition_level="accurate").recognize()  # [(text, conf, (x,y,w,h) normalized)]
    except Exception:
        return None


def text_stats(cap, shots, work: Path):
    hits, frames, sizes, ys, caps, colors = 0, 0, [], [], [], []
    for i, (a, b) in enumerate(shots[:: max(1, len(shots) // 60)]):
        f = _frame_at(cap, (a + b) / 2, 1280)
        if f is None:
            continue
        p = work / f"ocr_{i}.jpg"
        cv2.imwrite(str(p), f)
        res = ocr_frame(p)
        if res is None:
            return None  # OCR not available (non-Mac)
        frames += 1
        big = [r for r in res if r[1] > 0.6 and r[2][3] > 0.035 and len(r[0]) > 2]  # ignore tiny/watermark text
        if not big:
            continue
        hits += 1
        for txt, _, (x, y, w, h) in big:
            sizes.append(h)
            ys.append(1 - y - h / 2)  # Vision origin bottom-left → top-based center
            caps.append(sum(ch.isupper() for ch in txt) / max(1, sum(ch.isalpha() for ch in txt)))
            H, W = f.shape[:2]
            crop = f[int((1 - y - h) * H):int((1 - y) * H), int(x * W):int((x + w) * W)]
            if crop.size >= 30:
                px = crop.reshape(-1, 3).astype(np.float32)
                bright = px[px.sum(axis=1) >= np.percentile(px.sum(axis=1), 85)]
                if len(bright):
                    c = np.median(bright, axis=0)[::-1]  # BGR→RGB
                    if np.all(np.isfinite(c)):
                        colors.append(c.tolist())
    if not frames:
        return None
    pos = "center" if not ys else ("top" if np.median(ys) < 0.33 else "bottom" if np.median(ys) > 0.66 else "center")
    return {"overlay_rate": hits / frames, "position": pos, "height_ratio": float(np.median(sizes)) if sizes else 0.05,
            "caps_ratio": float(np.median(caps)) if caps else 1.0,
            "color_rgb": _safe_rgb(colors)}


def _safe_rgb(colors):
    if not colors:
        return [255, 255, 255]
    m = np.nanmedian(np.array(colors, dtype=np.float32), axis=0)
    return [int(x) if np.isfinite(x) else 255 for x in m]


def _try(log, what, fn, default):
    """Ek analysis step fail ho to poora analysis na ruke."""
    try:
        return fn()
    except Exception as e:
        _log(log, f"   ⚠ {what} skip ({type(e).__name__}: {str(e)[:120]})")
        return default


# ------------------------------------------------------------------ optional local vision model
def vision_notes(cap, times, model, log=None):
    import requests
    imgs = []
    for t in times[:4]:
        f = _frame_at(cap, t, 512)
        if f is not None:
            imgs.append(base64.b64encode(cv2.imencode(".jpg", f)[1]).decode())
    prompt = ("These are frames from one YouTube documentary. Describe ONLY the editing/visual style, as JSON: "
              '{"effects": ["film grain","vignette","glitch","VHS","black and white","red tint","blur background",'
              '"picture-in-picture","freeze frame","split screen", ...only those you see], '
              '"text_style": "how on-screen text looks", "framing": "how footage is framed", "mood": "3 words"}')
    try:
        r = requests.post("http://127.0.0.1:11434/api/generate", timeout=900, json={
            "model": model, "prompt": prompt, "images": imgs, "stream": False, "format": "json",
            "options": {"num_ctx": 4096}})
        j = r.json()
        if "response" not in j:
            _log(log, f"   vision model skip — Ollama error: {str(j.get('error', j))[:200]}")
            return None
        return json.loads(j["response"])
    except requests.exceptions.ConnectionError:
        _log(log, "   vision model skip — Ollama band hai. Terminal: `brew services start ollama`")
    except Exception as e:
        _log(log, f"   vision model skip ({type(e).__name__}: {str(e)[:150]})")
    return None


# ------------------------------------------------------------------ audio sfx
def _audio(video, work: Path):
    wav = work / f"{Path(video).stem}_16k.wav"
    if not wav.exists():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-ac", "1", "-ar", "16000", str(wav)], check=True)
    with wave.open(str(wav)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768, 16000


def sfx_at_cuts(audio, sr, cut_times):
    """Energy jump right at the cut vs the half-second before → sound effect. Spectral centroid → type."""
    found = {"whoosh": 0, "hit": 0, "riser": 0}
    win = int(0.05 * sr)
    for t in cut_times:
        i = int(t * sr)
        pre = audio[max(0, i - int(0.6 * sr)):max(0, i - int(0.15 * sr))]
        at = audio[max(0, i - int(0.15 * sr)):i + int(0.25 * sr)]
        if len(pre) < win or len(at) < win:
            continue
        e_pre, e_at = np.sqrt((pre ** 2).mean()) + 1e-6, np.sqrt((at ** 2).mean())
        if e_at / e_pre < 1.8:
            continue
        spec = np.abs(np.fft.rfft(at * np.hanning(len(at))))
        freqs = np.fft.rfftfreq(len(at), 1 / sr)
        cen = float((spec * freqs).sum() / (spec.sum() + 1e-9))
        # rising energy over the window before the cut = riser
        ramp = [np.sqrt((audio[max(0, i - k * win):max(1, i - (k - 1) * win)] ** 2).mean()) for k in (8, 6, 4, 2, 1)]
        if all(x < y for x, y in zip(ramp, ramp[1:])):
            found["riser"] += 1
        elif cen < 700:
            found["hit"] += 1
        else:
            found["whoosh"] += 1
    n = max(1, len(cut_times))
    return {k: v / n for k, v in found.items()}


# ------------------------------------------------------------------ main
def analyze(videos, work: Path, vision_model=None, log=None):
    work.mkdir(parents=True, exist_ok=True)
    shots_all, zooms, pans, trans, looks, texts, sfx, notes = [], [], [], [], [], [], [], []
    for v in videos:
        _log(log, f"   style: {Path(v).name} — cuts")
        shots = detect_cuts(v)
        if not shots:
            continue
        cap = cv2.VideoCapture(str(v))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        lens = [b - a for a, b in shots]
        shots_all += lens
        sample = shots[:: max(1, len(shots) // 80)]
        _log(log, f"   style: {len(shots)} shots — motion / transitions")
        for a, b in sample:
            z, p = _try(None, "motion", lambda: shot_motion(cap, a, b), (0.0, 0.0))
            if np.isfinite(z) and np.isfinite(p):
                zooms.append(z)
                pans.append(p)
        for a, _ in shots[1:: max(1, len(shots) // 60)]:
            trans.append(_try(None, "transition", lambda: classify_transition(cap, a, fps), "cut"))
        mids = [(a + b) / 2 for a, b in sample]
        lk = _try(log, "look", lambda: look_stats(cap, mids[:40]), None)
        if lk:
            looks.append(lk)
        _log(log, "   style: text / sfx")
        ts = _try(log, "text", lambda: text_stats(cap, shots, work), None)
        if ts:
            texts.append(ts)
        sf = _try(log, "sfx", lambda: sfx_at_cuts(*_audio(v, work), [a for a, _ in shots[1:]]), None)
        if sf:
            sfx.append(sf)
        if vision_model:
            n = vision_notes(cap, mids[:: max(1, len(mids) // 8)], vision_model, log)
            if n:
                notes.append(n)
        cap.release()
    if not shots_all:
        raise RuntimeError("style: koi shot detect nahi hua")
    z = np.array(zooms)
    moving = np.abs(z) > 0.006
    tcount = {k: trans.count(k) / max(1, len(trans)) for k in ("cut", "flash", "dip_to_black", "crossfade")}
    prof = {
        "pacing": {"median_shot_s": float(np.median(shots_all)), "p25_shot_s": float(np.percentile(shots_all, 25)),
                   "p75_shot_s": float(np.percentile(shots_all, 75)), "cuts_per_min": 60 / float(np.mean(shots_all))},
        "motion": {"moving_ratio": float(moving.mean()) if len(z) else 0,
                   "zoom_in_ratio": float((z > 0.006).sum() / max(1, moving.sum())),
                   "zoom_speed": float(np.median(np.abs(z[moving]))) if moving.any() else 0.0,
                   "pan_speed": float(np.median(np.abs(pans))) if pans else 0.0},
        "transitions": tcount,
        "look": {k: float(np.median([l[k] for l in looks])) for k in looks[0]} if looks else {},
        "text": ({k: (texts[0][k] if isinstance(texts[0][k], (str, list)) else float(np.median([t[k] for t in texts])))
                  for k in texts[0]} if texts else None),
        "sfx": {k: float(np.mean([s[k] for s in sfx])) for k in ("whoosh", "hit", "riser")} if sfx else {},
        "vision": notes,
    }
    prof = _clean(prof)
    (work / "style_profile.json").write_text(json.dumps(prof, indent=2))
    return prof


def _clean(x):
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_clean(v) for v in x]
    if isinstance(x, float) and not np.isfinite(x):
        return 0.0
    return x
