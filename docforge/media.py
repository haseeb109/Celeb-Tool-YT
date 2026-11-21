"""yt-dlp download, clip cutting, b-roll segments, final assembly (FFmpeg)."""
import json
import random
import shutil
import subprocess
from pathlib import Path

from rapidfuzz import fuzz

_ENC = None


def run(cmd, log=None):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        tail = p.stderr[-1500:]
        raise RuntimeError(f"command failed: {' '.join(map(str, cmd[:6]))} ...\n{tail}")
    return p.stdout


def duration(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)])
    return float(json.loads(out)["format"]["duration"])


def dims(quality):
    return (3840, 2160) if str(quality).lower() in ("4k", "2160p", "2160") else (1920, 1080)


def venc(cfg, W):
    global _ENC
    if _ENC is None:
        want = cfg["video"]["encoder"]
        encs = run(["ffmpeg", "-hide_banner", "-encoders"])
        _ENC = "h264_videotoolbox" if (want == "auto" and "h264_videotoolbox" in encs) else (
            want if want != "auto" else "libx264")
    br = "40M" if W > 2000 else "12M"
    if _ENC == "h264_videotoolbox":
        return ["-c:v", "h264_videotoolbox", "-b:v", br, "-maxrate", br, "-profile:v", "high", "-allow_sw", "1"]
    return ["-c:v", _ENC, "-preset", "veryfast", "-crf", "18", "-profile:v", "high"]


def common_out(cfg, W):
    return venc(cfg, W) + ["-pix_fmt", "yuv420p", "-r", str(cfg["video"]["fps"]), "-video_track_timescale", "30000",
                           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart"]


# ------------------------------------------------------------------ download
def download(link, out: Path, quality, log):
    if out.exists() and out.stat().st_size > 100_000:
        return out
    H = dims(quality)[1]
    fmt = f"bv*[height<={H}][vcodec^=avc1]+ba[ext=m4a]/bv*[height<={H}]+ba/b[height<={H}]/b"
    log(f"   yt-dlp ← {link}")
    run(["yt-dlp", "-f", fmt, "--merge-output-format", "mp4", "--no-playlist", "-o", str(out), link])
    return out


# ------------------------------------------------------------------ optional precise clip edges (Mac, mlx-whisper)
def refine_edges(src, start, end, quote, work: Path, log):
    """Line timestamps are coarse; tighten the clip to the exact first/last spoken word.
    Uses mlx-whisper if installed; otherwise returns the transcript bounds unchanged."""
    try:
        import mlx_whisper  # noqa
    except Exception:
        return start, end, "transcript"
    pad = 1.5
    s0 = max(0, start - pad)
    wav = work / f"win_{int(start * 1000)}.wav"
    run(["ffmpeg", "-y", "-ss", f"{s0}", "-t", f"{end - start + 2 * pad}", "-i", str(src), "-ac", "1", "-ar", "16000", str(wav)])
    try:
        r = mlx_whisper.transcribe(str(wav), path_or_hf_repo="mlx-community/whisper-large-v3-turbo", word_timestamps=True)
    except Exception as e:
        log(f"   mlx-whisper fail ({e}); transcript bounds use ho rahe hain")
        return start, end, "transcript"
    ws = [(w["word"].strip().lower(), w["start"] + s0, w["end"] + s0) for seg in r["segments"] for w in seg.get("words", [])]
    q = [w.strip(".,!?\"'").lower() for w in quote.split() if w.strip(".,!?\"'")]
    if len(ws) < 2 or len(q) < 2:
        return start, end, "transcript"

    def find(word_list, target_words, first=True):
        best, idx = 0, None
        rng = range(len(word_list)) if first else range(len(word_list) - 1, -1, -1)
        for i in rng:
            sc = fuzz.ratio(word_list[i][0].strip(".,!?\"'"), target_words)
            if sc > best:
                best, idx = sc, i
        return idx if best >= 70 else None

    i0 = find(ws, q[0], True)
    i1 = find(ws, q[-1], False)
    if i0 is None or i1 is None or i1 < i0:
        return start, end, "transcript"
    return max(0, ws[i0][1] - 0.12), ws[i1][2] + 0.25, "whisper"


# ------------------------------------------------------------------ segments
def cut_clip(src, start, end, out: Path, cfg, W, H, tag_png=None, trans="cut"):
    dur = end - start
    inputs = ["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src)]
    vf = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,"
          f"setsar=1,fps={cfg['video']['fps']}"
          + (",fade=t=in:st=0:d=0.18:color=white" if trans == "flash" else ",fade=t=in:st=0:d=0.3:color=black" if trans == "dip_to_black" else "")
          + "[v0]")
    last = "v0"
    if tag_png:
        inputs += ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(tag_png)]
        vf += f";[v0][1:v]overlay=0:0:shortest=1[v1]"
        last = "v1"
    af = (f"[0:a]aresample=48000,loudnorm=I=-15:TP=-1.5:LRA=11,afade=t=in:d=0.06,"
          f"afade=t=out:st={max(0, dur - 0.12):.3f}:d=0.12[a]")
    run(["ffmpeg", "-y", *inputs, "-filter_complex", vf + ";" + af, "-map", f"[{last}]", "-map", "[a]",
         "-t", f"{dur:.3f}", *common_out(cfg, W), str(out)])
    return out


def _shot_chain(n, src_i, d, fx, cfg, W, H, cw, ch, c):
    """One shot: edge-crop → cover → per-shot zoom/pan → transition-in (all from style profile)."""
    fps = cfg["video"]["fps"]
    z, pan, tr = fx.get("zoom", 0.0), fx.get("pan", 0.0), fx.get("trans", "cut")
    margin = 1.0 + abs(pan) * d + 0.02
    BW, BH = int(W * margin) // 2 * 2, int(H * margin) // 2 * 2
    f = (f"[{src_i}:v]crop=iw*{cw:.4f}:ih*{ch:.4f}:iw*{c['left'] / 100:.4f}:ih*{c['top'] / 100:.4f},"
         f"scale={BW}:{BH}:force_original_aspect_ratio=increase,crop={BW}:{BH},setsar=1,fps={fps}")
    if abs(z) > 0.001:
        grow = f"(1+{abs(z):.4f}*t)" if z > 0 else f"(1+{abs(z):.4f}*({d:.3f}-t))"
        f += f",scale=w='{BW}*{grow}':h=-2:eval=frame"
    x = f"(iw-{W})/2+{pan * W:.2f}*(t-{d / 2:.3f})" if abs(pan) > 0.001 else f"(iw-{W})/2"
    f += f",crop={W}:{H}:x='max(0,min(iw-{W},{x}))':y='(ih-{H})/2'"
    if tr == "flash":
        f += ",fade=t=in:st=0:d=0.18:color=white"
    elif tr == "dip_to_black":
        f += ",fade=t=in:st=0:d=0.3:color=black"
    return f + f",format=yuv420p[s{n}]"


def finish_chain(look, W, H):
    """Look elements measured on the competitor (letterbox / vignette / grain)."""
    out = ""
    if look.get("letterbox", 0) > 0.04:
        bar = int(H * look["letterbox"]) // 2 * 2
        out += f",drawbox=x=0:y=0:w={W}:h={bar}:color=black:t=fill,drawbox=x=0:y={H - bar}:w={W}:h={bar}:color=black:t=fill"
    if look.get("vignette_ratio", 1) < 0.72:
        out += ",vignette=PI/4.5"
    if look.get("grain", 0) > 6:
        out += f",noise=alls={min(18, int(look['grain']))}:allf=t"
    return out


def broll_segment(shots, vo_mp3, out: Path, cfg, W, H, card_png=None, gap=0.35, look=None):
    """shots: [(src_path, start, dur, fx)] — muted footage cut to VO length, edited per style profile."""
    vo_d = duration(vo_mp3)
    total = vo_d + gap
    seq, acc, i = [], 0.0, 0
    while acc < total + 0.5 and shots:
        s = shots[i % len(shots)]
        seq.append(s)
        acc += s[2]
        i += 1
        if i > 300:
            break
    c = cfg["video"]["broll_crop"]
    cw, ch = 1 - (c["left"] + c["right"]) / 100, 1 - (c["top"] + c["bottom"]) / 100
    args, chains = [], []
    for n, sh in enumerate(seq):
        src, st, d = sh[0], sh[1], sh[2]
        fx = sh[3] if len(sh) > 3 else {}
        args += ["-ss", f"{st:.3f}", "-t", f"{d:.3f}", "-i", str(src)]
        chains.append(_shot_chain(n, n, d, fx, cfg, W, H, cw, ch, c))
    k = len(seq)
    fc = ";".join(chains) + ";" + "".join(f"[s{n}]" for n in range(k)) + f"concat=n={k}:v=1:a=0,trim=0:{total:.3f},setpts=PTS-STARTPTS"
    if cfg["video"]["broll_grade"]:
        fc += ",eq=saturation=0.72:contrast=1.1:brightness=-0.035,vignette=PI/4.5"
    fc += finish_chain(look or {}, W, H) + "[bv]"
    last = "bv"
    args += ["-i", str(vo_mp3)]
    if card_png:
        show = min(6.5, total - 0.6)
        args += ["-loop", "1", "-t", f"{show:.3f}", "-i", str(card_png)]
        fc += (f";[{k + 1}:v]format=rgba,fade=t=in:st=0:d=0.35:alpha=1,fade=t=out:st={max(0, show - 0.4):.3f}:d=0.4:alpha=1,"
               f"setpts=PTS-STARTPTS+0.5/TB[cd];[bv][cd]overlay=0:0:eof_action=pass[bv2]")
        last = "bv2"
    fc += f";[{k}:a]aresample=48000,apad=whole_dur={total:.3f}[a]"
    run(["ffmpeg", "-y", *args, "-filter_complex", fc, "-map", f"[{last}]", "-map", "[a]",
         "-t", f"{total:.3f}", *common_out(cfg, W), str(out)])
    # cut points inside this segment (for sound effects)
    cuts, t = [], 0.0
    for sh in seq[:-1]:
        t += sh[2]
        if t < total - 0.3:
            cuts.append((t, (sh[3] if len(sh) > 3 else {}).get("trans", "cut")))
    return out, total, cuts


def concat(parts, out: Path):
    lst = out.with_suffix(".txt")
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(out)])
    return out


def music_bed(folder: Path, total, out: Path, seed, work: Path):
    files = sorted([p for p in folder.glob("*") if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")])
    if not files:
        return None
    random.Random(seed).shuffle(files)
    dec, acc, i = [], 0.0, 0
    while acc < total + 2:
        f = files[i % len(files)]
        w = work / f"m_{i % len(files)}_{f.stem[:20]}.wav"
        if not w.exists():
            run(["ffmpeg", "-y", "-i", str(f), "-ar", "48000", "-ac", "2", str(w)])
        dec.append(w)
        acc += duration(w)
        i += 1
    lst = work / "music.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in dec))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-t", f"{total:.3f}",
         "-af", f"afade=t=in:d=2,afade=t=out:st={max(0, total - 4):.3f}:d=4", str(out)])
    return out


def final_mix(video: Path, music: Path, out: Path, cfg, W, srt: Path = None, stems_dir: Path = None, sfx: Path = None):
    m = cfg["music"]
    burn = srt is not None and srt.exists()
    args = ["ffmpeg", "-y", "-i", str(video)]
    voice = "[0:a]"
    pre = ""
    if sfx:  # sound effects ride on the voice bus (so music ducks under them too)
        args += ["-i", str(sfx)]
        si = 1
        pre = f"[0:a][{si}:a]amix=inputs=2:duration=first:normalize=0[vx];"
        voice = "[vx]"
    if music:
        mi = 2 if sfx else 1
        args += ["-i", str(music)]
        duck = "[mv][vk]sidechaincompress=threshold=0.025:ratio=10:attack=15:release=450[md]" if m["duck"] else "[mv]anull[md]"
        fa = (pre + f"[{mi}:a]volume={m['volume_db']}dB[mv];{voice}asplit=2[vk][vo];{duck};"
              f"[vo][md]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1:LRA=11[a]")
    else:
        fa = pre + f"{voice}loudnorm=I=-14:TP=-1:LRA=11[a]"
    if burn:
        style = "FontName=Arial Black,FontSize=15,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,MarginV=60"
        srt_esc = str(srt.resolve()).replace(":", r"\:").replace("'", r"\'")
        fv = f"[0:v]subtitles='{srt_esc}':force_style='{style}'[v]"
        args += ["-filter_complex", fa + ";" + fv, "-map", "[v]", "-map", "[a]", *common_out(cfg, W)]
    else:
        args += ["-filter_complex", fa, "-map", "0:v", "-map", "[a]", "-c:v", "copy",
                 "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-movflags", "+faststart"]
    run(args + [str(out)])
    if stems_dir:
        stems_dir.mkdir(exist_ok=True)
        run(["ffmpeg", "-y", "-i", str(video), "-vn", "-ar", "48000", str(stems_dir / "voice_and_clips.wav")])
        if music:
            run(["ffmpeg", "-y", "-i", str(music), "-af", f"volume={m['volume_db']}dB", str(stems_dir / "music.wav")])
        if sfx:
            shutil.copy(sfx, stems_dir / "sfx.wav")
    return out


def grab_frame(video, t, out: Path):
    run(["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(out)])
    return out


def have(binary):
    return shutil.which(binary) is not None
