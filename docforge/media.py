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
def cut_clip(src, start, end, out: Path, cfg, W, H, tag_png=None):
    dur = end - start
    inputs = ["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src)]
    vf = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black,"
          f"setsar=1,fps={cfg['video']['fps']}[v0]")
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


def broll_segment(shots, vo_mp3, out: Path, cfg, W, H, card_png=None, gap=0.35):
    """shots: [(src_path, start, dur)]  — muted footage cut to VO length."""
    vo_d = duration(vo_mp3)
    total = vo_d + gap
    seq, acc, i = [], 0.0, 0
    while acc < total + 0.5 and shots:
        s = shots[i % len(shots)]
        seq.append(s)
        acc += s[2]
        i += 1
        if i > 200:
            break
    c = cfg["video"]["broll_crop"]
    cw, ch = 1 - (c["left"] + c["right"]) / 100, 1 - (c["top"] + c["bottom"]) / 100
    BW, BH = int(W * 1.08) // 2 * 2, int(H * 1.08) // 2 * 2
    args, chains = [], []
    for n, (src, st, d) in enumerate(seq):
        args += ["-ss", f"{st:.3f}", "-t", f"{d:.3f}", "-i", str(src)]
        chains.append(f"[{n}:v]crop=iw*{cw:.4f}:ih*{ch:.4f}:iw*{c['left'] / 100:.4f}:ih*{c['top'] / 100:.4f},"
                      f"scale={BW}:{BH}:force_original_aspect_ratio=increase,crop={BW}:{BH},setsar=1,"
                      f"fps={cfg['video']['fps']},format=yuv420p[s{n}]")
    k = len(seq)
    fc = ";".join(chains) + ";" + "".join(f"[s{n}]" for n in range(k)) + f"concat=n={k}:v=1:a=0,trim=0:{total:.3f},setpts=PTS-STARTPTS[cat]"
    fc += f";[cat]crop={W}:{H}:x='(iw-{W})*(0.5+0.5*sin(t/6))':y='(ih-{H})*(0.5+0.5*cos(t/9))'"
    if cfg["video"]["broll_grade"]:
        fc += ",eq=saturation=0.72:contrast=1.1:brightness=-0.035,vignette=PI/4.5"
    fc += "[bv]"
    last = "bv"
    ai = k
    args += ["-i", str(vo_mp3)]
    if card_png:
        show = min(6.5, total - 0.6)
        args += ["-loop", "1", "-t", f"{show:.3f}", "-i", str(card_png)]
        fc += (f";[{k + 1}:v]format=rgba,fade=t=in:st=0:d=0.35:alpha=1,fade=t=out:st={max(0, show - 0.4):.3f}:d=0.4:alpha=1,"
               f"setpts=PTS-STARTPTS+0.5/TB[cd];[bv][cd]overlay=0:0:eof_action=pass[bv2]")
        last = "bv2"
    fc += f";[{ai}:a]aresample=48000,apad=whole_dur={total:.3f}[a]"
    run(["ffmpeg", "-y", *args, "-filter_complex", fc, "-map", f"[{last}]", "-map", "[a]",
         "-t", f"{total:.3f}", *common_out(cfg, W), str(out)])
    return out, total


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


def final_mix(video: Path, music: Path, out: Path, cfg, W, srt: Path = None, stems_dir: Path = None):
    m = cfg["music"]
    burn = srt is not None and srt.exists()
    args = ["ffmpeg", "-y", "-i", str(video)]
    if music:
        args += ["-i", str(music)]
        duck = "[mv][vk]sidechaincompress=threshold=0.025:ratio=10:attack=15:release=450[md]" if m["duck"] else "[mv]anull[md]"
        fa = (f"[1:a]volume={m['volume_db']}dB[mv];[0:a]asplit=2[vk][vo];{duck};"
              f"[vo][md]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1:LRA=11[a]")
    else:
        fa = "[0:a]loudnorm=I=-14:TP=-1:LRA=11[a]"
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
    return out


def grab_frame(video, t, out: Path):
    run(["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(out)])
    return out


def have(binary):
    return shutil.which(binary) is not None
