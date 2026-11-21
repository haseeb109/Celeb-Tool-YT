#!/usr/bin/env python3
"""DocForge CLI

  python run.py doctor                      # sab tools/keys check
  python run.py voices                      # ElevenLabs voices list
  python run.py run                         # jobs/ ki saari pending/failed jobs (bulk)
  python run.py run jobs/<id>               # ek job
  python run.py run jobs/<id> --from voice  # kisi stage se dobara (jaise voice badalni ho)
  python run.py run --voice "Dark Narrator" # sab jobs is voice se
  python run.py new --link1 URL --t1 file.txt --link2 URL --t2 file.txt --rumor "..."
  python run.py relock                      # master prompt jaan boojh kar badla ho to
"""
import argparse
import subprocess
import sys
from pathlib import Path

from docforge.config import load_config, master_prompt_text, relock
from docforge.jobs import create_job, list_jobs
from docforge.pipeline import STAGES, run_job


def doctor():
    import os, shutil
    cfg = load_config()
    ok = True

    def chk(name, cond, hint=""):
        nonlocal ok
        print(f"  {'✔' if cond else '✖'} {name}" + ("" if cond else f"   → {hint}"))
        ok &= bool(cond)

    for b in ("ffmpeg", "ffprobe", "yt-dlp"):
        chk(b, shutil.which(b), "./install.sh chalao")
    try:
        enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
        print(f"  {'✔' if 'h264_videotoolbox' in enc else '•'} h264_videotoolbox (Apple hardware encoder)")
        flt = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
        print(f"  {'✔' if ' subtitles ' in flt else '•'} libass subtitles filter (sirf subtitles ke liye zaroori)")
    except Exception:
        pass
    try:
        import mlx_whisper  # noqa
        print("  ✔ mlx-whisper (clip edges word-level precise)")
    except Exception:
        print("  • mlx-whisper nahi — clips transcript timestamps par kategi (thodi loose)")
    try:
        master_prompt_text(cfg)
        chk("master prompt lock", True)
    except Exception as e:
        chk("master prompt lock", False, str(e).splitlines()[0])
    chk("DEPLOY_API_KEY", os.environ.get("DEPLOY_API_KEY"), ".env mein daalo")
    chk("ELEVENLABS_API_KEY", os.environ.get("ELEVENLABS_API_KEY"), ".env mein daalo")
    music = list((Path(__file__).parent / cfg["music"]["folder"]).glob("*.*"))
    print(f"  {'✔' if music else '•'} music files: {len(music)}")
    if os.environ.get("DEPLOY_API_KEY"):
        try:
            from docforge.llm import LLM
            r = LLM(cfg).client.chat.completions.create(model=cfg["llm"]["writer_model"], max_tokens=5,
                                                       messages=[{"role": "user", "content": "say ok"}],
                                                       extra_body={"reasoning_effort": "none"})
            chk(f"Deploy API ({cfg['llm']['writer_model']})", r.choices)
        except Exception as e:
            chk("Deploy API", False, str(e)[:150])
    return ok


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    sub.add_parser("voices")
    sub.add_parser("relock")
    sub.add_parser("list")
    st = sub.add_parser("style", help="competitor style analyze + lock")
    st.add_argument("--name", required=True)
    st.add_argument("sources", nargs="+", help="YouTube links ya video files")
    st.add_argument("--lock", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("job", nargs="?")
    r.add_argument("--from", dest="frm", choices=STAGES)
    r.add_argument("--voice")
    r.add_argument("--retry-failed", action="store_true", default=True)
    n = sub.add_parser("new")
    n.add_argument("--name", default="")
    n.add_argument("--link1", required=True)
    n.add_argument("--t1", required=True)
    n.add_argument("--link2", default="")
    n.add_argument("--t2", default="")
    n.add_argument("--rumor", required=True)
    n.add_argument("--quality", choices=["1080p", "4k"])
    n.add_argument("--voice")
    a = ap.parse_args()

    if a.cmd == "doctor":
        sys.exit(0 if doctor() else 1)
    if a.cmd == "relock":
        print("new sha256:", relock())
    if a.cmd == "voices":
        from docforge.tts import list_voices
        for name, vid, cat in list_voices():
            print(f"  {name:35s} {vid}  ({cat})")
    if a.cmd == "style":
        from docforge import styles
        slug, prof = styles.analyze_reference(a.sources, a.name)
        print(styles.summary(prof).replace("**", ""))
        if a.lock:
            styles.lock(slug)
            print(f"🔒 locked: {slug}")
    if a.cmd == "list":
        for j in list_jobs():
            print(f"  {j['state']:8s} {j['stages_done']}/{len(STAGES)}  {j['job']}  {j['error']}")
    if a.cmd == "new":
        d = create_job(a.name, a.link1, Path(a.t1).read_text(), a.link2,
                       Path(a.t2).read_text() if a.t2 else "", a.rumor, a.quality, a.voice)
        print("created", d)
    if a.cmd == "run":
        targets = [Path(a.job)] if a.job else [j["path"] for j in list_jobs() if j["state"] != "done"]
        if not targets:
            print("koi pending job nahi")
        failed = []
        for t in targets:
            try:
                run_job(t, a.frm, a.voice)
            except Exception:
                failed.append(t.name)  # bulk: ek job fail ho to agli chalti rahe
        print(f"\nDone: {len(targets) - len(failed)}/{len(targets)}" + (f"  failed: {failed}" if failed else ""))


if __name__ == "__main__":
    main()
