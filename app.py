#!/usr/bin/env python3
"""Celeb Tool YT — local GUI  →  python app.py  →  http://127.0.0.1:7860"""
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
STAGE_LABELS = ["Download", "Style", "Plan", "Script", "QA", "Clips", "Voice", "Visuals", "Assemble", "Package"]
CSS = """
.gradio-container {max-width: 1400px !important}
#title h1 {margin-bottom: 0}
.stage-done {color:#2ea043} .stage-todo {color:#666}
"""


# ------------------------------------------------------------------ helpers
def voices(provider=None):
    try:
        from docforge import tts
        if provider:
            tts.PROVIDER["name"] = provider
        return [f"{n}  ::  {v}" for n, v, _ in tts.list_voices()]
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


def job_names(done_only=False):
    return [j["job"] for j in list_jobs() if (j["state"] == "done" or not done_only)]


def tail():
    cur = _worker["current"]
    if not cur or not (Path(cur) / "log.txt").exists():
        return "(queue idle)"
    return "\n".join((Path(cur) / "log.txt").read_text().splitlines()[-45:])


# ------------------------------------------------------------------ actions
def add_job(name, l1, t1, f1, l2, t2, f2, rumor, quality, voice, subs):
    t1, t2 = read_txt(f1, t1), read_txt(f2, t2)
    if not (l1.strip() and t1.strip() and rumor.strip()):
        return "✖ Link 1, Transcript 1 aur Rumor zaroori hain", jobs_table()
    d = create_job(name, l1, t1, l2, t2, rumor, quality, _vid(voice), subs)
    return f"✔ Queue mein add: **{d.name}**", jobs_table()


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
        return "Job select karo", jobs_table()
    shutil.rmtree(ROOT / load_config()["paths"]["jobs"] / job, ignore_errors=True)
    return f"🗑 {job} delete (output folder rakha hai)", jobs_table()


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
def keys_save(dk, ek, ak):
    save_keys(dk or None, ek or None, ak or None)
    return ("✔ Keys save ho gayin (.env, sirf aapke Mac par)", mask("DEPLOY_API_KEY"), mask("ELEVENLABS_API_KEY"),
            mask("AI33_API_KEY"), "", "", "")


def test_deploy(dk):
    from docforge.llm import diagnose_deploy
    if dk:
        save_keys(dk, None, None)
    report, base = diagnose_deploy(load_config())
    if base:
        save_local({"llm": {"base_url": base}})
        report += f"\n\n✔ Deploy chal raha hai. Base URL lock: {base}"
    else:
        report += "\n\n✖ Koi URL kaam nahi kiya — upar har line ka status code aur wajah dekho."
    return f"```\n{report}\n```", mask("DEPLOY_API_KEY")


def test_voice(provider, key):
    env = "AI33_API_KEY" if provider == "ai33" else "ELEVENLABS_API_KEY"
    if key:
        save_keys(None, key if provider == "elevenlabs" else None, key if provider == "ai33" else None)
    v = voices(provider)
    ok = v and not v[0].startswith("(error")
    return f"✔ {provider} chal raha hai: {len(v)} voices" if ok else f"✖ {provider}: {v[0] if v else 'no voices'}", mask(env)


def do_update():
    from docforge.updater import restart_soon, update
    changed, log = update()
    if changed:
        restart_soon()
    return f"```\n{log}\n```" + ("\n\n**Page 5 second baad refresh kar lena.**" if changed else "")


# settings
def settings_save(provider, writer, auditor, w_eff, a_eff, voice, model_id, speed, quality, subs, crop_t, crop_b,
                  grade, cards, tag, mvol, duck):
    save_local({
        "llm": {"writer_model": writer, "auditor_model": auditor, "writer_reasoning": w_eff, "auditor_reasoning": a_eff},
        "voice": {"provider": provider, "voice": _vid(voice) or "", "model_id": model_id, "speed": float(speed)},
        "video": {"quality": quality, "subtitles": bool(subs), "broll_crop": {"top": int(crop_t), "bottom": int(crop_b), "left": 0, "right": 0},
                  "broll_grade": bool(grade), "label_cards": bool(cards), "clip_tag": "ORIGINAL CLIP" if tag else ""},
        "music": {"volume_db": int(mvol), "duck": bool(duck)},
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


def doctor_text():
    import subprocess, sys
    r = subprocess.run([sys.executable, str(ROOT / "run.py"), "doctor"], capture_output=True, text=True, cwd=ROOT)
    return r.stdout + r.stderr


# ------------------------------------------------------------------ UI
cfg = load_config()
THEME = gr.themes.Base(primary_hue="red", neutral_hue="zinc")
GR6 = int(gr.__version__.split(".")[0]) >= 6
STYLE = {"css": CSS, "theme": THEME}
with gr.Blocks(title="Celeb Tool YT", **({} if GR6 else STYLE)) as ui:
    with gr.Row():
        gr.Markdown("# 🎬 Celeb Tool YT\nDark documentary pipeline · master prompt locked", elem_id="title")
        upd = gr.Button("⬆ Update tool", scale=0, size="sm")
    upd_msg = gr.Markdown()

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
        with gr.Row():
            quality = gr.Radio(["1080p", "4k"], value=cfg["video"]["quality"], label="Quality")
            voice = gr.Dropdown(choices=[], value=cfg["voice"]["voice"] or None, label="Voice (khaali = Settings wali)", allow_custom_value=True, scale=2)
            vref = gr.Button("↻ Voices load", scale=0)
            subs = gr.Checkbox(label="Subtitles", value=cfg["video"]["subtitles"])
        add = gr.Button("➕ Add to Queue", variant="primary", size="lg")
        add_msg = gr.Markdown()

    with gr.Tab("⏳ Queue"):
        gr.Markdown("Stages: " + " → ".join(STAGE_LABELS))
        grid = gr.Dataframe(headers=["Job", "Status", "Stages", "Error"], value=jobs_table, interactive=False, wrap=True)
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

    with gr.Tab("🔑 API Keys"):
        gr.Markdown("Keys sirf aapke Mac par `.env` file mein save hoti hain. GitHub par kabhi nahi jati (`.gitignore`).")
        with gr.Row():
            with gr.Column():
                gr.Markdown("### Deploy.com (DeepSeek / GLM)")
                dstat = gr.Markdown(mask("DEPLOY_API_KEY"))
                dkey = gr.Textbox(label="DEPLOY_API_KEY", type="password", placeholder="naya key paste karo")
                dtest = gr.Button("Test Deploy (saare URLs check karta hai)")
            with gr.Column():
                gr.Markdown("### ElevenLabs")
                estat = gr.Markdown(mask("ELEVENLABS_API_KEY"))
                ekey = gr.Textbox(label="ELEVENLABS_API_KEY", type="password", placeholder="naya key paste karo")
                etest = gr.Button("Test ElevenLabs")
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
                s_prov = gr.Radio(["elevenlabs", "ai33"], value=cfg["voice"].get("provider", "elevenlabs"), label="Voice provider")
                s_voice = gr.Dropdown(choices=[], value=cfg["voice"]["voice"] or None, label="Default voice", allow_custom_value=True)
                s_vref = gr.Button("↻ Voices load")
                s_model = gr.Textbox(cfg["voice"]["model_id"], label="ElevenLabs model")
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
        btn.click(lambda: gr.Dropdown(choices=voices(load_config()["voice"].get("provider"))), None, dd)
    s_vref.click(lambda p: gr.Dropdown(choices=voices(p)), s_prov, s_voice)
    upd.click(do_update, None, upd_msg)
    add.click(add_job, [name, l1, t1, f1, l2, t2, f2, rumor, quality, voice, subs], [add_msg, grid])
    go.click(start_queue, qvoice, qmsg)
    rbtn.click(rerun, [rjob, rstage, qvoice], qmsg)
    dbtn.click(delete_job, rjob, [qmsg, grid])
    oref.click(lambda: gr.Dropdown(choices=job_names()), None, ojob)
    ojob.change(load_output, ojob, [ovid, oscript, olog, oqa, opk, ofiles])
    ksave.click(keys_save, [dkey, ekey, akey], [kmsg, dstat, estat, astat, dkey, ekey, akey])
    dtest.click(test_deploy, dkey, [kmsg, dstat])
    etest.click(lambda k: test_voice("elevenlabs", k), ekey, [kmsg, estat])
    atest.click(lambda k: test_voice("ai33", k), akey, [kmsg, astat])
    ssave.click(settings_save, [s_prov, s_writer, s_aud, s_weff, s_aeff, s_voice, s_model, s_speed, s_q, s_subs, s_ct, s_cb,
                                s_grade, s_cards, s_tag, s_mvol, s_duck], smsg)
    m_up.upload(music_add, m_up, m_tbl)
    m_clr.click(music_clear, None, m_tbl)
    doc_btn.click(doctor_text, None, doc_out)
    timer = gr.Timer(3)
    timer.tick(lambda: (jobs_table(), tail(), gr.Dropdown(choices=job_names())), None, [grid, log, rjob])

if __name__ == "__main__":
    ui.launch(server_name="127.0.0.1", server_port=7860, inbrowser=True, allowed_paths=[str(ROOT / "output")],
              **(STYLE if GR6 else {}))
