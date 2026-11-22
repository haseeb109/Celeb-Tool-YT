#!/usr/bin/env python3
"""Celeb Studio — local GUI  →  python app.py  →  http://127.0.0.1:7860"""
import json
import os
import shutil
import threading
from pathlib import Path

import gradio as gr

from docforge.config import ROOT, load_config, mask, save_keys, save_local
from docforge.jobs import create_job, list_jobs
from docforge.pipeline import STAGES, run_job

_worker = {"thread": None, "current": None}
STAGE_LABELS = ["Download", "Style", "B-roll", "Plan", "Script", "QA", "Clips", "Voice", "Visuals", "Assemble", "Package"]
from docforge import ui_theme as T
from docforge import version as V
CSS = T.CSS


# ------------------------------------------------------------------ helpers
def voices(search="", source=""):
    try:
        from docforge import tts
        return [tts.label(v) for v in tts.list_voices(search, source)]
    except Exception as e:
        return [f"(error: {str(e)[:80]})"]


def _vid(choice):
    return choice.split("::")[-1].strip() if choice and "::" in choice else (choice or None)


def read_txt(file, text):
    if file:
        return Path(file).read_text(errors="ignore")
    return text or ""


def jobs_table():
    rows = []
    for j in list_jobs():
        st = json.loads((j["path"] / "status.json").read_text()) if (j["path"] / "status.json").exists() else {"done": []}
        bar = " ".join(("✅" if s in st.get("done", []) else "⬜") for s in STAGES)
        icon = {"done": "✔ done", "running": "⏳ running", "failed": "✖ failed"}.get(j["state"], "• pending")
        rows.append([j["job"], icon, bar, j["error"]])
    return rows


def queue_cards():
    js = []
    for j in list_jobs():
        sf = j["path"] / "status.json"
        js.append({**j, "status": json.loads(sf.read_text()) if sf.exists() else {}})
    return T.queue_html(js, STAGES, STAGE_LABELS)


def update_state():
    """Header button: naya version hai to 'Update to vX', warna 'Latest ✓'."""
    try:
        r = V.remote()
    except Exception:
        r = None
    cur = V.current()
    if r and r["behind"] > 0:
        return gr.Button(value=f"⟳  Update to {r['label']}", elem_classes=[])
    return gr.Button(value=f"✓  {cur['label']} · latest", elem_classes=["latest"])


def startup_toast():
    u = V.just_updated()
    if u:
        old, cur, changes = u
        return T.toast_html(f"Updated {old} → {cur['label']}", changes)
    return ""


def job_names(done_only=False):
    return [j["job"] for j in list_jobs() if (j["state"] == "done" or not done_only)]


def tail():
    cur = _worker["current"]
    if not cur or not (Path(cur) / "log.txt").exists():
        return "(queue idle)"
    return "\n".join((Path(cur) / "log.txt").read_text().splitlines()[-45:])


# ------------------------------------------------------------------ actions
def add_job(name, l1, t1, f1, l2, t2, f2, rumor, subject, blinks, quality, voice, subs):
    t1, t2 = read_txt(f1, t1), read_txt(f2, t2)
    if not (l1.strip() and t1.strip() and rumor.strip()):
        return "✖ Link 1, Transcript 1 aur Rumor zaroori hain", queue_cards()
    d = create_job(name, l1, t1, l2, t2, rumor, quality, _vid(voice), subs, subject, blinks)
    return f"✔ Queue mein add: **{d.name}**", queue_cards()


def _loop(voice):
    tried = set()
    while True:
        pend = [j for j in list_jobs() if j["state"] in ("pending", "failed", "running") and j["job"] not in tried]
        if not pend:
            break
        j = pend[0]
        tried.add(j["job"])
        _worker["current"] = j["path"]
        try:
            run_job(j["path"], None, voice)
        except Exception:
            pass
    _worker["current"] = None


def start_queue(voice):
    if _worker["thread"] and _worker["thread"].is_alive():
        return "Queue pehle se chal rahi hai"
    _worker["thread"] = threading.Thread(target=_loop, args=(_vid(voice),), daemon=True)
    _worker["thread"].start()
    return "▶ Queue start"


def rerun(job, stage_label, voice):
    if not job:
        return "Job select karo"
    if _worker["thread"] and _worker["thread"].is_alive():
        return "Queue chal rahi hai, khatam hone do"
    stage = STAGES[STAGE_LABELS.index(stage_label)]
    path = ROOT / load_config()["paths"]["jobs"] / job

    def go():
        _worker["current"] = path
        try:
            run_job(path, stage, _vid(voice))
        except Exception:
            pass
        _worker["current"] = None
    _worker["thread"] = threading.Thread(target=go, daemon=True)
    _worker["thread"].start()
    return f"▶ {job}: '{stage_label}' se dobara"


def delete_job(job):
    if not job:
        return "Job select karo", queue_cards()
    shutil.rmtree(ROOT / load_config()["paths"]["jobs"] / job, ignore_errors=True)
    return f"🗑 {job} delete (output folder rakha hai)", queue_cards()


def load_output(job):
    empty = (None, "", [], "", "", [])
    if not job:
        return empty
    out = ROOT / load_config()["paths"]["output"] / job
    if not out.exists():
        return empty
    vid = next(iter(sorted(out.glob("*.mp4"))), None)
    script = (out / "script.md").read_text() if (out / "script.md").exists() else "(script abhi nahi bani)"
    rows = []
    if (out / "clip_log.csv").exists():
        import csv
        rows = [[r["clip"], r["source"], r["quote"], r["placement"], r["source_timestamp"], r["video_position"], r["length"]]
                for r in csv.DictReader(open(out / "clip_log.csv"))]
    qa = (out / "qa_report.json").read_text() if (out / "qa_report.json").exists() else ""
    pk = (out / "packaging.md").read_text() if (out / "packaging.md").exists() else ""
    files = [str(p) for p in sorted(out.rglob("*")) if p.is_file()]
    return str(vid) if vid else None, script, rows, qa, pk, files


# keys
def keys_save(dk, ak):
    save_keys(dk or None, ak or None)
    return "✔ Keys save ho gayin (.env, sirf aapke Mac par)", mask("DEPLOY_API_KEY"), mask("AI33_API_KEY"), "", ""


def test_deploy(dk):
    from docforge.llm import diagnose_deploy
    if dk:
        save_keys(dk, None)
    report, base = diagnose_deploy(load_config())
    if base:
        save_local({"llm": {"base_url": base}})
        report += f"\n\n✔ Deploy chal raha hai. Base URL lock: {base}"
    else:
        report += "\n\n✖ Koi URL kaam nahi kiya — upar har line ka status code aur wajah dekho."
    return f"```\n{report}\n```", mask("DEPLOY_API_KEY")


def test_ai33(key):
    if key:
        save_keys(None, key)
    v = voices()
    ok = v and not v[0].startswith("(error")
    return (f"✔ AI33 Pro chal raha hai: {len(v)} voices mili" if ok else f"✖ AI33: {v[0] if v else 'koi voice nahi'}"), mask("AI33_API_KEY")


def voice_search(q, src):
    v = voices(q or "", src or "elevenlabs")
    if v and v[0].startswith("(error"):
        return gr.Dropdown(choices=[], value=None), v[0]
    return gr.Dropdown(choices=v, value=v[0] if v else None), f"{len(v)} voices"


def voice_preview(choice):
    from docforge import tts
    vid = _vid(choice)
    url = tts.preview_url(vid) if vid else ""
    return url or None


def do_update():
    from docforge.updater import restart_soon, update
    old = V.current()["label"]
    changed, log = update()
    if changed:
        restart_soon()
        new = V.current()["label"]
        items = [l.lstrip("• ") for l in log.splitlines() if l.startswith("• ")]
        return T.toast_html(f"Updated {old} → {new} · tool restart ho raha hai, 5 sec baad page refresh karo", items)
    if "latest" in log:
        return T.toast_html(f"{old} — tool pehle se latest hai ✓")
    return f"```\n{log}\n```"


# settings
def settings_save(y_ck, b_src, b_n, b_days, b_img, b_dir, writer, auditor, w_eff, a_eff, voice, model_id, speed, quality, subs, crop_t, crop_b,
                  grade, cards, tag, mvol, duck):
    save_local({
        "llm": {"writer_model": writer, "auditor_model": auditor, "writer_reasoning": w_eff, "auditor_reasoning": a_eff},
        "voice": {"voice": _vid(voice) or "", "model_id": model_id, "speed": float(speed)},
        "video": {"quality": quality, "subtitles": bool(subs), "broll_crop": {"top": int(crop_t), "bottom": int(crop_b), "left": 0, "right": 0},
                  "broll_grade": bool(grade), "label_cards": bool(cards), "clip_tag": "ORIGINAL CLIP" if tag else ""},
        "music": {"volume_db": int(mvol), "duck": bool(duck)},
        "youtube": {"cookies_from_browser": y_ck or ""},
        "broll": {"source": b_src, "target_clips": int(b_n), "recent_days": int(b_days), "images": int(b_img),
                  "local_folder": (b_dir or "").strip()},
    })
    return "✔ Settings save (settings.local.yaml)"


def music_list():
    d = ROOT / load_config()["music"]["folder"]
    return [[p.name, f"{p.stat().st_size / 1e6:.1f} MB"] for p in sorted(d.glob("*")) if p.suffix.lower() in
            (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")]


def music_add(files):
    d = ROOT / load_config()["music"]["folder"]
    d.mkdir(parents=True, exist_ok=True)
    for f in files or []:
        shutil.copy(f, d / Path(f).name)
    return music_list()


def music_clear():
    d = ROOT / load_config()["music"]["folder"]
    for p in d.glob("*"):
        if p.name != ".keep":
            p.unlink()
    return music_list()


_style_job = {"thread": None, "log": []}


def style_analyze(l1, l2, l3, f, name):
    from docforge import styles
    if _style_job["thread"] and _style_job["thread"].is_alive():
        return "Analysis pehle se chal raha hai"
    srcs = [x for x in (l1, l2, l3) if x and x.strip()] + ([f] if f else [])
    if not srcs or not name.strip():
        return "✖ Kam az kam 1 link/video aur style ka naam do"
    _style_job["log"] = []

    def go():
        try:
            styles.analyze_reference(srcs, name.strip(), lambda m: _style_job["log"].append(m))
        except Exception as e:
            _style_job["log"].append(f"✖ {e}")
    _style_job["thread"] = threading.Thread(target=go, daemon=True)
    _style_job["thread"].start()
    return "▶ Analysis shuru (video ki length ke hisaab se 3–15 min)"


def style_log():
    return "\n".join(_style_job["log"][-30:]) or "(idle)"


def style_view(slug):
    from docforge import styles
    return styles.summary(styles.load(slug)) if slug else ""


def style_lock(slug):
    from docforge import styles
    styles.lock(slug)
    return f"🔒 Locked: **{slug}** — ab har nayi job isi style mein banegi", lock_status()


def style_unlock():
    from docforge import styles
    styles.lock("")
    return "🔓 Unlock — har job apni source videos se style naapegi", lock_status()


def lock_status():
    from docforge import styles
    lk = styles.locked()
    return f"### 🔒 Locked style: **{lk}**" if lk else "### 🔓 Koi style lock nahi"


def quick_download(url):
    import subprocess
    if not url or not url.strip().startswith("http"):
        return "✖ Link do"
    out = ROOT / load_config()["paths"]["output"] / "downloads"
    out.mkdir(parents=True, exist_ok=True)
    from docforge.media import ytdlp_args
    p = subprocess.run(["yt-dlp", *ytdlp_args(), "-f", "bv*[vcodec^=avc1]+ba[ext=m4a]/bv*+ba/b", "--merge-output-format", "mp4", "-N", "8",
                        "--no-playlist", "-o", str(out / "%(title).80s [%(id)s].%(ext)s"), url.strip()],
                       capture_output=True, text=True)
    return f"✔ Saved in `{out}`" if p.returncode == 0 else f"✖ {(p.stderr or p.stdout)[-300:]}"


def doctor_text():
    import subprocess, sys
    r = subprocess.run([sys.executable, str(ROOT / "run.py"), "doctor"], capture_output=True, text=True, cwd=ROOT)
    return r.stdout + r.stderr


# ------------------------------------------------------------------ UI
cfg = load_config()
THEME = gr.themes.Base(primary_hue="blue", neutral_hue="slate", font=[gr.themes.GoogleFont("Inter"), gr.themes.Font("system-ui"), gr.themes.Font("sans-serif")])
GR6 = int(gr.__version__.split(".")[0]) >= 6
STYLE = {"css": CSS, "theme": THEME}
with gr.Blocks(title="Celeb Studio", **({} if GR6 else STYLE)) as ui:
    _ver = V.current()
    with gr.Row(elem_id="ice-head"):
        gr.HTML(T.brand_html(), elem_classes=["ice-plain"], scale=3)
        with gr.Row(elem_id="ice-actions", scale=2):
            ver_chip = gr.HTML(T.chip_html(_ver), elem_classes=["ice-plain"])
            theme_btn = gr.Button("☾ Dark", elem_id="ice-theme", variant="secondary", size="sm", scale=0)
            upd = gr.Button(f"⟳  {_ver['label']}", elem_id="ice-update", size="sm", scale=0)
    upd_msg = gr.HTML(elem_classes=["ice-plain"])

    with gr.Tab("➕ New Job"):
        name = gr.Textbox(label="Job name (optional)", placeholder="jaise: drake-vs-kendrick")
        with gr.Row():
            with gr.Column():
                gr.Markdown("### Video 1")
                l1 = gr.Textbox(label="YouTube link", placeholder="https://www.youtube.com/watch?v=...")
                gr.Markdown("**Transcript 1** (timestamps ke saath) — paste karo YA upload")
                with gr.Tabs():
                    with gr.Tab("📋 Paste"):
                        t1 = gr.Textbox(show_label=False, lines=14, max_lines=40, placeholder="Yahan transcript paste karo (Cmd+V)\n[00:00:05] text...\n[00:00:09] text...")
                    with gr.Tab("📁 Upload"):
                        f1 = gr.File(show_label=False, file_types=[".txt", ".srt", ".vtt"], type="filepath")
            with gr.Column():
                gr.Markdown("### Video 2")
                l2 = gr.Textbox(label="YouTube link", placeholder="https://www.youtube.com/watch?v=...")
                gr.Markdown("**Transcript 2** (timestamps ke saath) — paste karo YA upload")
                with gr.Tabs():
                    with gr.Tab("📋 Paste"):
                        t2 = gr.Textbox(show_label=False, lines=14, max_lines=40, placeholder="Yahan transcript paste karo (Cmd+V)\n[00:00:05] text...\n[00:00:09] text...")
                    with gr.Tab("📁 Upload"):
                        f2 = gr.File(show_label=False, file_types=[".txt", ".srt", ".vtt"], type="filepath")
        rumor = gr.Textbox(label="🔥 Main rumor / idea (1 line), poori video isi ke gird", lines=2)
        subject = gr.Textbox(label="🎯 Celebrity name — AI voice ke neeche isi ki internet clips aur photos aayengi (khaali = AI khud nikalega)",
                             placeholder="jaise: Keanu Reeves")
        blinks = gr.Textbox(label="🎞 B-roll source links — har line mein ek link (YouTube / Instagram reel / TikTok). Sirf inhi se b-roll banega, har clip sirf ek dafa. Khaali = auto search",
                            lines=6, placeholder="https://www.youtube.com/watch?v=...\nhttps://www.instagram.com/reel/...\nhttps://www.tiktok.com/@user/video/...")
        with gr.Row():
            quality = gr.Radio(["1080p", "4k"], value=cfg["video"]["quality"], label="Quality")
            voice = gr.Dropdown(choices=[], value=cfg["voice"]["voice"] or None, label="AI33 voice (khaali = Settings wali)", allow_custom_value=True, scale=2)
            vref = gr.Button("↻ Voices load", scale=0)
            subs = gr.Checkbox(label="Subtitles", value=cfg["video"]["subtitles"])
        add = gr.Button("➕ Add to Queue", variant="primary", size="lg")
        add_msg = gr.Markdown()

    with gr.Tab("⏳ Queue"):
        grid = gr.HTML(queue_cards)
        with gr.Row():
            qvoice = gr.Dropdown(choices=[], label="Voice override (optional)", allow_custom_value=True)
            qref = gr.Button("↻ Voices", scale=0)
            go = gr.Button("▶ Run Queue", variant="primary")
        qmsg = gr.Markdown()
        with gr.Accordion("Ek job dobara chalao / delete", open=False):
            with gr.Row():
                rjob = gr.Dropdown(choices=job_names(), label="Job", allow_custom_value=True)
                rstage = gr.Dropdown(STAGE_LABELS, value="Voice", label="Is stage se dobara")
                rbtn = gr.Button("↺ Re-run")
                dbtn = gr.Button("🗑 Delete job", variant="stop")
        log = gr.Code(label="Live log", value=tail, language=None, lines=22)

    with gr.Tab("🎞 Outputs"):
        with gr.Row():
            ojob = gr.Dropdown(choices=job_names(), label="Job", allow_custom_value=True, scale=3)
            oref = gr.Button("↻", scale=0)
        ovid = gr.Video(label="Final video")
        with gr.Tab("Script"):
            oscript = gr.Markdown()
        with gr.Tab("Clip log"):
            olog = gr.Dataframe(headers=["Clip", "Source", "Quote", "Placement", "Source timestamp", "Video position", "Length"], wrap=True)
        with gr.Tab("QA report"):
            oqa = gr.Code(language="json")
        with gr.Tab("Titles / description"):
            opk = gr.Markdown()
        with gr.Tab("Files"):
            ofiles = gr.Files()

    with gr.Tab("🎨 Style"):
        st_status = gr.Markdown(lock_status)
        with gr.Row():
            with gr.Column():
                gr.Markdown("### 1. Competitor ki video(s) do\nEk hi channel ki 1–3 videos do, style zyada accurate aayega.")
                st_name = gr.Textbox(label="Style ka naam", placeholder="jaise: cloutville-dark")
                st_l1 = gr.Textbox(label="Video link 1", placeholder="https://www.youtube.com/watch?v=...")
                st_l2 = gr.Textbox(label="Video link 2 (optional)")
                st_l3 = gr.Textbox(label="Video link 3 (optional)")
                st_f = gr.File(label="…ya video file upload (mp4)", type="filepath")
                st_go = gr.Button("🔍 Analyze style", variant="primary")
                st_msg = gr.Markdown()
                st_log = gr.Code(label="Analysis log", value=style_log, language=None, lines=10)
            with gr.Column():
                gr.Markdown("### 2. Saved styles → Lock")
                with gr.Row():
                    st_pick = gr.Dropdown(choices=[], label="Style", allow_custom_value=False, scale=3)
                    st_ref = gr.Button("↻", scale=0)
                st_sum = gr.Markdown()
                with gr.Row():
                    st_lock = gr.Button("🔒 Lock this style", variant="primary")
                    st_unlock = gr.Button("🔓 Unlock")
                st_lmsg = gr.Markdown()
                gr.Markdown("*Ye sirf video ki editing par asar karta hai (pacing, zoom, transitions, text, look, sound effects). Script aur master prompt ke rules wahi rehte hain.*")

    with gr.Tab("🔑 API Keys"):
        gr.Markdown("Keys sirf aapke Mac par `.env` file mein save hoti hain. GitHub par kabhi nahi jati (`.gitignore`).")
        with gr.Row():
            with gr.Column():
                gr.Markdown("### Deploy.com (DeepSeek / GLM)")
                dstat = gr.Markdown(mask("DEPLOY_API_KEY"))
                dkey = gr.Textbox(label="DEPLOY_API_KEY", type="password", placeholder="naya key paste karo")
                dtest = gr.Button("Test Deploy (saare URLs check karta hai)")
            with gr.Column():
                gr.Markdown("### AI33 Pro")
                astat = gr.Markdown(mask("AI33_API_KEY"))
                akey = gr.Textbox(label="AI33_API_KEY", type="password", placeholder="naya key paste karo")
                atest = gr.Button("Test AI33 Pro")
        ksave = gr.Button("💾 Save keys", variant="primary")
        kmsg = gr.Markdown()

    with gr.Tab("⚙️ Settings"):
        with gr.Row():
            with gr.Column():
                gr.Markdown("### Brain")
                s_writer = gr.Textbox(cfg["llm"]["writer_model"], label="Writer model")
                s_weff = gr.Dropdown(["none", "low", "high", "max"], value=cfg["llm"]["writer_reasoning"], label="Writer reasoning")
                s_aud = gr.Textbox(cfg["llm"]["auditor_model"], label="Auditor model (QA Phase 2)")
                s_aeff = gr.Dropdown(["low", "high", "max"], value=cfg["llm"]["auditor_reasoning"], label="Auditor reasoning")
            with gr.Column():
                gr.Markdown("### Voice")
                gr.Markdown("**AI33 Pro**")
                with gr.Row():
                    s_vq = gr.Textbox(label="Search", placeholder="jaise: deep male, narrator, british", scale=3)
                    s_src = gr.Dropdown(["elevenlabs"], value="elevenlabs", label="Voice library", scale=1)
                s_vref = gr.Button("🔍 Voices dhoondo / load")
                s_vcount = gr.Markdown()
                s_voice = gr.Dropdown(choices=[], value=cfg["voice"]["voice"] or None, label="Default voice (ya voice_id paste karo)", allow_custom_value=True)
                s_prev = gr.Audio(label="Preview sun lo", interactive=False)
                s_model = gr.Dropdown(["eleven_multilingual_v2", "eleven_turbo_v2_5", "eleven_flash_v2_5"], value=cfg["voice"]["model_id"], label="AI33 voice model", allow_custom_value=True)
                s_speed = gr.Slider(0.8, 1.2, value=cfg["voice"].get("speed", 1.0), step=0.01, label="Speed")
            with gr.Column():
                gr.Markdown("### Video")
                s_q = gr.Radio(["1080p", "4k"], value=cfg["video"]["quality"], label="Default quality")
                s_subs = gr.Checkbox(value=cfg["video"]["subtitles"], label="Subtitles default")
                s_ct = gr.Slider(0, 30, value=cfg["video"]["broll_crop"]["top"], step=1, label="B-roll crop top % (logo)")
                s_cb = gr.Slider(0, 30, value=cfg["video"]["broll_crop"]["bottom"], step=1, label="B-roll crop bottom % (burned subtitles)")
                gr.Markdown("*Ye teen master prompt ka hissa nahi, default off:*")
                s_grade = gr.Checkbox(value=cfg["video"]["broll_grade"], label="Dark color grade")
                s_cards = gr.Checkbox(value=cfg["video"]["label_cards"], label="ALLEGED / CONFIRMED cards")
                s_tag = gr.Checkbox(value=bool(cfg["video"]["clip_tag"]), label="'ORIGINAL CLIP' tag")
        with gr.Row():
            with gr.Column():
                gr.Markdown("### 🎞 B-roll (AI voice ke neeche, hook ke baad)")
                b_src = gr.Radio([("Internet clips + photos", "internet"), ("Internet + competitor mix", "mix"), ("Sirf competitor footage", "competitor")],
                                 value=cfg.get("broll", {}).get("source", "internet"), label="Footage source")
                b_n = gr.Slider(10, 80, value=cfg.get("broll", {}).get("target_clips", 40), step=5, label="Internet clips (5/8/10s)")
                b_days = gr.Dropdown([("Last 30 din", 30), ("Last 90 din", 90), ("Last 1 saal", 365), ("Koi limit nahi", 0)],
                                     value=cfg.get("broll", {}).get("recent_days", 90), label="Pehle kitni recent clips (kam milein to purani bhi)")
                b_img = gr.Slider(0, 30, value=cfg.get("broll", {}).get("images", 12), step=1, label="Photos (animated, Wikimedia)")
                b_dir = gr.Textbox(cfg.get("broll", {}).get("local_folder", ""), label="Apna videos folder (optional, shuffle hoga)",
                                   placeholder="/Users/haseeb/Movies/keanu")
                gr.Markdown("### ▶ YouTube")
                y_ck = gr.Dropdown([("Off", ""), ("Chrome", "chrome"), ("Safari", "safari"), ("Firefox", "firefox"), ("Brave", "brave"), ("Edge", "edge")],
                                   value=(cfg.get("youtube", {}) or {}).get("cookies_from_browser", ""),
                                   label="Browser cookies — 'not a bot' error aaye to woh browser chuno jismein YouTube login hai")
            with gr.Column():
                gr.Markdown("### 📥 Quick Download (MediaForge)")
                qd_url = gr.Textbox(label="YouTube / Instagram / TikTok / X link")
                qd_go = gr.Button("Download MP4")
                qd_out = gr.Markdown()
        with gr.Row():
            with gr.Column():
                gr.Markdown("### Music (ek dafa lock, har video mein yahi)")
                m_up = gr.File(label="Music files add karo", file_count="multiple", file_types=["audio"], type="filepath")
                m_tbl = gr.Dataframe(headers=["File", "Size"], value=music_list, interactive=False)
                m_clr = gr.Button("Music folder khaali karo", variant="stop", size="sm")
                s_mvol = gr.Slider(-35, -8, value=cfg["music"]["volume_db"], step=1, label="Music volume (dB)")
                s_duck = gr.Checkbox(value=cfg["music"]["duck"], label="Voice ke neeche music dabao (ducking)")
            with gr.Column():
                gr.Markdown("### System check")
                doc_btn = gr.Button("🩺 Run doctor")
                doc_out = gr.Code(language=None, lines=14)
        ssave = gr.Button("💾 Save settings", variant="primary")
        smsg = gr.Markdown()
        gr.Markdown("🔒 Master prompt ke rules locked hain. Ye settings unhein nahi badal sakti.")

    # wiring
    for btn, dd in ((vref, voice), (qref, qvoice)):
        btn.click(lambda: gr.Dropdown(choices=voices()), None, dd)
    s_vref.click(voice_search, [s_vq, s_src], [s_voice, s_vcount])
    s_vq.submit(voice_search, [s_vq, s_src], [s_voice, s_vcount])
    s_voice.change(voice_preview, s_voice, s_prev)
    upd.click(do_update, None, upd_msg)
    theme_btn.click(None, None, None, js=T.TOGGLE_JS)
    ui.load(None, None, None, js=T.THEME_JS)
    ui.load(startup_toast, None, upd_msg)
    ui.load(update_state, None, upd)
    from docforge import styles as _st
    st_go.click(style_analyze, [st_l1, st_l2, st_l3, st_f, st_name], st_msg)
    st_ref.click(lambda: gr.Dropdown(choices=_st.list_styles(), value=_st.locked() or None), None, st_pick)
    st_pick.change(style_view, st_pick, st_sum)
    st_lock.click(style_lock, st_pick, [st_lmsg, st_status])
    st_unlock.click(style_unlock, None, [st_lmsg, st_status])
    ui.load(lambda: gr.Dropdown(choices=_st.list_styles(), value=_st.locked() or None), None, st_pick)
    add.click(add_job, [name, l1, t1, f1, l2, t2, f2, rumor, subject, blinks, quality, voice, subs], [add_msg, grid])
    go.click(start_queue, qvoice, qmsg)
    rbtn.click(rerun, [rjob, rstage, qvoice], qmsg)
    dbtn.click(delete_job, rjob, [qmsg, grid])
    oref.click(lambda: gr.Dropdown(choices=job_names()), None, ojob)
    ojob.change(load_output, ojob, [ovid, oscript, olog, oqa, opk, ofiles])
    ksave.click(keys_save, [dkey, akey], [kmsg, dstat, astat, dkey, akey])
    dtest.click(test_deploy, dkey, [kmsg, dstat])
    atest.click(test_ai33, akey, [kmsg, astat])
    qd_go.click(quick_download, qd_url, qd_out)
    ssave.click(settings_save, [y_ck, b_src, b_n, b_days, b_img, b_dir, s_writer, s_aud, s_weff, s_aeff, s_voice, s_model, s_speed, s_q, s_subs, s_ct, s_cb,
                                s_grade, s_cards, s_tag, s_mvol, s_duck], smsg)
    m_up.upload(music_add, m_up, m_tbl)
    m_clr.click(music_clear, None, m_tbl)
    doc_btn.click(doctor_text, None, doc_out)
    timer = gr.Timer(3)
    timer.tick(lambda: (queue_cards(), tail(), gr.Dropdown(choices=job_names()), style_log()), None, [grid, log, rjob, st_log])

if __name__ == "__main__":
    ui.launch(server_name="127.0.0.1", server_port=7860, inbrowser=True, allowed_paths=[str(ROOT / "output")],
              **(STYLE if GR6 else {}))
