"""Orchestrator. Every stage writes its result into jobs/<id>/work/ and is skipped on re-run (resume)."""
import csv
import json
import random
from concurrent.futures import ThreadPoolExecutor
import time
import traceback
from pathlib import Path

import yaml

from . import media, overlays, packaging, sfx, style, tts
from .config import ROOT, load_config, master_prompt_text
from .llm import LLM
from .qa import run_qa
from .script_engine import (clean_segments, make_plan, narration_words, register_clips, render_markdown,
                            write_montage, write_section, clip_log_rows)
from .transcript import Transcript, fmt

WORKERS = 3  # parallel FFmpeg jobs (M1 Pro: 3 safe; videotoolbox ke saath)
STAGES = ["ingest", "style", "plan", "write", "qa", "clips", "voice", "visuals", "assemble", "package"]


class Job:
    def __init__(self, path: Path, cfg):
        self.dir = path
        self.cfg = cfg
        self.spec = yaml.safe_load((path / "job.yaml").read_text())
        self.id = path.name
        self.work = path / "work"
        self.work.mkdir(exist_ok=True)
        self.out = ROOT / cfg["paths"]["output"] / self.id
        self.out.mkdir(parents=True, exist_ok=True)
        self.status_file = path / "status.json"
        self.quality = self.spec.get("quality") or cfg["video"]["quality"]
        self.W, self.H = media.dims(self.quality)
        self.logf = open(path / "log.txt", "a")

    def log(self, msg):
        line = f"[{time.strftime('%H:%M:%S')}] [{self.id}] {msg}"
        print(line, flush=True)
        self.logf.write(line + "\n")
        self.logf.flush()

    # status
    def status(self):
        return json.loads(self.status_file.read_text()) if self.status_file.exists() else {"done": [], "state": "pending"}

    def mark(self, stage=None, state=None, error=None):
        s = self.status()
        if stage and stage not in s["done"]:
            s["done"].append(stage)
        if state:
            s["state"] = state
        s["error"] = error
        s["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.status_file.write_text(json.dumps(s, indent=2))

    def reset_from(self, stage):
        s = self.status()
        i = STAGES.index(stage)
        s["done"] = [x for x in s["done"] if STAGES.index(x) < i]
        s["state"] = "pending"
        self.status_file.write_text(json.dumps(s, indent=2))

    def j(self, name, data=None):
        p = self.work / name
        if data is None:
            return json.loads(p.read_text())
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        return data

    def transcripts(self):
        ts = []
        for n in (1, 2):
            f = self.dir / f"transcript{n}.txt"
            if f.exists() and f.read_text().strip():
                ts.append(Transcript(n, f.read_text()))
        if not ts:
            raise RuntimeError("koi transcript nahi mila (transcript1.txt / transcript2.txt)")
        return ts


def run_job(path: Path, force_from=None, voice_override=None):
    cfg = load_config()
    master_prompt_text(cfg)  # lock check before spending anything
    global WORKERS
    WORKERS = int(cfg["video"].get("parallel_jobs", 3))
    job = Job(Path(path), cfg)
    if force_from:
        job.reset_from(force_from)
    done = job.status()["done"]
    job.mark(state="running")
    llm = None
    try:
        ts = job.transcripts()
        src = {}
        for stage in STAGES:
            if stage in done:
                continue
            job.log(f"▶ {stage}")
            if stage in ("plan", "write", "qa", "package") and llm is None:
                llm = LLM(cfg, job.log)
            globals()[f"stage_{stage}"](job, cfg, ts, llm, voice_override=voice_override)
            job.mark(stage)
        job.mark(state="done")
        job.log(f"✔ DONE → {job.out}")
    except Exception as e:
        job.log("✖ " + "".join(traceback.format_exception_only(type(e), e)).strip())
        job.logf.write(traceback.format_exc())
        job.mark(state="failed", error=str(e)[:500])
        raise
    finally:
        if llm:
            job.log(f"   tokens: {llm.usage}")


def srcfile(job, n):
    return job.work / f"source{n}.mp4"


# ------------------------------------------------------------------ stages
def stage_ingest(job, cfg, ts, llm, **_):
    for t in ts:
        if not job.spec.get(f"link{t.src}"):
            raise RuntimeError(f"link{t.src} job.yaml mein nahi")
    with ThreadPoolExecutor(max_workers=2) as ex:  # dono videos ek saath download
        list(ex.map(lambda t: media.download(job.spec[f"link{t.src}"], srcfile(job, t.src), job.quality, job.log), ts))
    for t in ts:
        d = media.duration(srcfile(job, t.src))
        last = t.lines[-1].start
        if last > d + 5:
            raise RuntimeError(f"Transcript {t.src} ka last timestamp {fmt(last)} video ({fmt(d)}) se lamba hai — galat transcript/link?")
        job.log(f"   source{t.src}: {fmt(d)}, {len(t.lines)} transcript lines")
    job.j("transcripts.json", {t.src: t.to_dict() for t in ts})


def stage_style(job, cfg, ts, llm, **_):
    if not cfg["video"].get("replicate_style"):
        job.j("style_profile.json", {})
        job.log("   replicate_style off — skip")
        return
    from . import styles
    lk = styles.locked()
    if lk:  # locked competitor style → har job mein yahi
        job.j("style_profile.json", styles.load(lk))
        job.log(f"   🔒 locked style: {lk}")
        return
    prof = style.analyze([srcfile(job, t.src) for t in ts], job.work / "style",
                         cfg["video"].get("vision_model") or None, job.log)
    job.j("style_profile.json", prof)
    p, m, tr = prof["pacing"], prof["motion"], prof["transitions"]
    job.log(f"   pacing: shot {p['median_shot_s']:.1f}s median ({p['cuts_per_min']:.0f} cuts/min) · "
            f"motion {m['moving_ratio']:.0%} shots (zoom-in {m['zoom_in_ratio']:.0%}) · "
            f"transitions {', '.join(f'{k} {v:.0%}' for k, v in tr.items() if v)} · sfx {prof.get('sfx')}")


def _profile(job):
    p = job.work / "style_profile.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _fx(prof, rng, d):
    """Per-shot effect sampled from the measured distributions."""
    if not prof:
        return {}
    m, tr = prof["motion"], prof["transitions"]
    fx = {"trans": rng.choices(list(tr), weights=list(tr.values()))[0] if sum(tr.values()) else "cut"}
    if rng.random() < m["moving_ratio"]:
        sp = m["zoom_speed"] * rng.uniform(0.8, 1.2)
        fx["zoom"] = sp if rng.random() < m["zoom_in_ratio"] else -sp
        if m.get("pan_speed", 0) > 0.003:
            fx["pan"] = m["pan_speed"] * rng.choice([-1, 1])
    return fx


def _shot_len(prof, rng):
    if not prof:
        return 4.5
    p = prof["pacing"]
    return max(0.8, min(8.0, rng.uniform(p["p25_shot_s"], p["p75_shot_s"])))


def stage_plan(job, cfg, ts, llm, **_):
    plan = make_plan(llm, cfg, job.spec, ts, job.log)
    clips = register_clips(plan, ts)
    job.j("plan.json", plan)
    job.j("clips.json", clips)
    job.log(f"   plan: {len(plan['sections'])} sections, {len(clips)} clips")


def stage_write(job, cfg, ts, llm, **_):
    plan, clips = job.j("plan.json"), job.j("clips.json")
    sections = []
    m_ids = [c for c in clips if clips[c]["montage"]]
    segs, missing = clean_segments(write_montage(llm, cfg, job.spec, ts, plan, clips), m_ids, ts)
    if segs and segs[0]["type"] != "clip":  # enforce: open on a clip
        first = next((s for s in segs if s["type"] == "clip"), None)
        if first:
            segs.remove(first)
            segs.insert(0, first)
    sections.append({"id": "S0", "heading": "OPENING MONTAGE", "segments": segs})
    prev = " ".join(s["text"] for s in segs if s["type"] == "narration")
    for sec in plan["sections"]:
        segs, missing = clean_segments(write_section(llm, cfg, job.spec, ts, plan, clips, sec, prev), sec["clip_ids"], ts)
        if missing:
            job.log(f"   {sec['id']}: clips {missing} place nahi huin → retry")
            segs2, missing2 = clean_segments(write_section(llm, cfg, job.spec, ts, plan, clips, sec, prev,
                                             extra=f"\nIMPORTANT: you MUST place these clip refs: {sec['clip_ids']}\n"), sec["clip_ids"], ts)
            if len(missing2) < len(missing):
                segs = segs2
        sections.append({"id": sec["id"], "heading": sec["heading"], "segments": segs})
        prev = " ".join(s["text"] for s in segs if s["type"] == "narration")
        job.log(f"   {sec['id']} written ({sum(len(s['text'].split()) for s in segs if s['type'] == 'narration')} words)")
    script = {"title": plan.get("working_title", job.id), "clips": clips, "sections": sections,
              "wps": cfg["script"]["words_per_second"]}
    job.j("script.json", script)


def stage_qa(job, cfg, ts, llm, **_):
    script, plan = job.j("script.json"), job.j("plan.json")
    report, ok = run_qa(llm, cfg, job.spec, ts, script, plan, job.log)
    job.j("script.json", script)
    job.j("qa_report.json", {"passed": ok, "rounds": report})
    md = render_markdown(script)
    (job.out / "script.md").write_text(md)
    (job.out / "qa_report.json").write_text(json.dumps({"passed": ok, "rounds": report}, indent=2, ensure_ascii=False))
    if not ok:
        raise RuntimeError("QA: master prompt ke major rules abhi bhi toot rahe hain — video nahi banegi. "
                           "output/<job>/qa_report.json dekho; dobara: run.py run jobs/<id> --from write")
    job.log(f"   final narration: {narration_words(script)} words")


def stage_clips(job, cfg, ts, llm, **_):
    script = job.j("script.json")
    d = job.work / "clips"
    d.mkdir(exist_ok=True)
    tag = None
    if cfg["video"]["clip_tag"]:
        tag = overlays.clip_tag(cfg["video"]["clip_tag"], job.W, job.H, job.work / "clip_tag.png", ROOT / cfg["paths"]["fonts"])
    used = {s["ref"] for sec in script["sections"] for s in sec["segments"] if s["type"] == "clip"}
    prof = _profile(job)
    tr = prof.get("transitions", {})
    for cid in used:  # word-level edges (whisper, GPU) — ek ek karke
        c = script["clips"][cid]
        st, en, how = media.refine_edges(srcfile(job, c["src"]), c["start"], c["end"], c["quote"], job.work, job.log)
        c["cut_start"], c["cut_end"], c["edge_source"] = st, en, how

    def cut(cid):
        c = script["clips"][cid]
        trans = random.Random(cid + job.id).choices(list(tr), weights=list(tr.values()))[0] if tr and sum(tr.values()) else "cut"
        media.cut_clip(srcfile(job, c["src"]), c["cut_start"], c["cut_end"], d / f"{cid}.mp4", cfg, job.W, job.H, tag, trans,
                       prof.get("clip_frame", "pad"))
        job.log(f"   {cid} T{c['src']} {fmt(c['cut_start'])}–{fmt(c['cut_end'])} ({c['cut_end'] - c['cut_start']:.1f}s, {c['edge_source']})")
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:  # FFmpeg cuts parallel
        list(ex.map(cut, sorted(used)))
    job.j("script.json", script)


def stage_voice(job, cfg, ts, llm, voice_override=None, **_):
    script = job.j("script.json")
    vname = voice_override or job.spec.get("voice") or cfg["voice"]["voice"]
    if not vname:  # koi voice select nahi → account ki pehli voice
        vs = tts.list_voices()
        if not vs:
            raise RuntimeError("Account mein koi voice nahi mili — Settings → Voices load se voice chuno ya voice_id paste karo")
        vname = vs[0]["id"]
        job.log(f"   ⚠ voice select nahi thi → pehli voice use: {vs[0]['name']} ({vname}). Badalni ho: Settings → Default voice")
    vid = tts.resolve_voice(vname)
    job.log(f"   AI33 voice: {vname} → {vid}")
    d = job.work / "voice"
    d.mkdir(exist_ok=True)
    narr = [(si, gi, s) for si, sec in enumerate(script["sections"]) for gi, s in enumerate(sec["segments"]) if s["type"] == "narration"]
    def say(item):
        si, gi, s = item
        out = d / f"n_{si:02d}_{gi:02d}.mp3"
        s["align"] = tts.synth(s["text"], vid, cfg["voice"], out, "", "", ROOT / ".cache" / "tts")
        s["vo"] = str(out)
    with ThreadPoolExecutor(max_workers=6) as ex:  # AI33 tasks ek saath (rate limit 10/s)
        list(ex.map(say, narr))
    job.log(f"   {len(narr)} voiceover blocks")
    lo, hi = cfg["script"]["runtime_minutes"]
    clips_s = sum(c.get("cut_end", c["end"]) - c.get("cut_start", c["start"])
                  for c in script["clips"].values() if any(x.get("ref") == c["id"] for sec in script["sections"] for x in sec["segments"]))
    total = sum(media.duration(s["vo"]) + 0.35 for _, _, s in narr) + clips_s
    job.log(f"   runtime with this voice: {fmt(total)}")
    if not (lo * 60 <= total <= hi * 60) and not job.spec.get("_speed_adjusted"):
        target = (lo + hi) / 2 * 60
        sp = cfg["voice"].get("speed", 1.0) * (total - clips_s) / max(1, target - clips_s)
        sp = max(0.8, min(1.15, sp))
        job.log(f"   runtime 17–20 min se bahar → voice speed {sp:.2f} par dobara")
        cfg["voice"]["speed"] = sp
        with ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(lambda it: it[2].update(align=tts.synth(it[2]["text"], vid, cfg["voice"], Path(it[2]["vo"]), "", "",
                                                                 ROOT / ".cache" / "tts")), narr))
        total = sum(media.duration(s["vo"]) + 0.35 for _, _, s in narr) + clips_s
        job.log(f"   new runtime: {fmt(total)}")
    if not (lo * 60 <= total <= hi * 60):
        job.j("script.json", script)
        raise RuntimeError(f"Runtime {fmt(total)} — master prompt 17–20 min mangta hai. "
                           f"config.yaml mein script.min_words/max_words ya voice.speed adjust karke --from write chalao")
    job.j("script.json", script)


def _fallback_shots(job, ts, used_ranges, k):
    """Agar model ne b-roll range nahi di: un ranges se footage lo jo clips mein use nahi huin."""
    pool = []
    for t in ts:
        for l in t.lines[::4]:
            if not any(t.src == s and a <= l.start <= b for s, a, b in used_ranges):
                pool.append((srcfile(job, t.src), l.start, min(5.0, max(2.5, l.end - l.start))))
    return pool[k % max(1, len(pool)):][:4] or pool[:4]


def stage_visuals(job, cfg, ts, llm, **_):
    script = job.j("script.json")
    tm = {t.src: t for t in ts}
    d = job.work / "segments"
    d.mkdir(exist_ok=True)
    fonts = ROOT / cfg["paths"]["fonts"]
    clip_ranges = [(c["src"], c["start"], c["end"]) for c in script["clips"].values()]
    prof = _profile(job)
    rng = random.Random(job.id)
    k, tasks = 0, []
    for si, sec in enumerate(script["sections"]):
        for gi, s in enumerate(sec["segments"]):
            if s["type"] != "narration":
                continue
            out = d / f"n_{si:02d}_{gi:02d}.mp4"
            shots = []
            for b in s.get("broll", []):
                st, en, _, _ = tm[b["src"]].span(b["lines"])
                pos = st
                while pos < en - 0.8:
                    L = min(_shot_len(prof, rng), en - pos)
                    shots.append((srcfile(job, b["src"]), pos, L, _fx(prof, rng, L)))
                    pos += L
            if not shots:
                shots = [(a, b_, _shot_len(prof, rng), _fx(prof, rng, 3)) for a, b_, _ in _fallback_shots(job, ts, clip_ranges, k)]
            card = None
            tstyle = prof.get("text") if prof else None
            use_cards = cfg["video"]["label_cards"] or (tstyle and tstyle.get("overlay_rate", 0) >= 0.15)
            if use_cards and s.get("card"):
                card = overlays.label_card(s["card"]["kind"].upper(), s["card"]["text"], job.W, job.H,
                                           job.work / f"card_{si:02d}_{gi:02d}.png", fonts, tstyle)
            tasks.append((s, shots, out, card))
            k += 1

    def render(t):
        s, shots, out, card = t
        _, tot, cuts = media.broll_segment(shots, Path(s["vo"]), out, cfg, job.W, job.H, card,
                                           look=prof.get("look") if prof else None,
                                           grade=prof.get("grade") if prof else None)
        s["seg"], s["seg_dur"], s["cuts"] = str(out), tot, cuts
    done = [0]

    def render_logged(t):
        render(t)
        done[0] += 1
        if done[0] % 10 == 0 or done[0] == len(tasks):
            job.log(f"   visuals {done[0]}/{len(tasks)} segments")
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:  # segments parallel render
        list(ex.map(render_logged, tasks))
    job.j("script.json", script)


def stage_assemble(job, cfg, ts, llm, **_):
    script = job.j("script.json")
    parts, t, placements, sec_starts, srt = [], 0.0, {}, [], []
    cut_ev, clip_ev = [], []
    for sec in script["sections"]:
        sec_starts.append(("Intro" if sec["id"] == "S0" else sec["heading"], t))
        for s in sec["segments"]:
            if s["type"] == "clip":
                p = job.work / "clips" / f"{s['ref']}.mp4"
                placements[s["ref"]] = t
                clip_ev.append(t)
                parts.append(p)
                t += media.duration(p)
            else:
                for (w, a, b) in _chunk_words(tts.words_from_alignment(s["align"])):
                    srt.append((t + a, t + b, w))
                cut_ev += [(t + ct, tr) for ct, tr in s.get("cuts", [])]
                if parts:
                    cut_ev.append((t, "cut"))
                parts.append(Path(s["seg"]))
                t += media.duration(s["seg"])
    tag = "4k" if job.W > 2000 else "1080p"
    full = media.concat(parts, job.work / "full_nomusic.mp4")
    srt_path = None
    cap = (_profile(job) or {}).get("captions")
    if cap and cap.get("enabled", True) and job.spec.get("subtitles", True) is not False:
        from .captions import write_ass
        ws = []
        for a, b, chunk in srt:
            toks = chunk.split()
            step = (b - a) / max(1, len(toks))
            ws += [(t, a + k * step, a + (k + 1) * step) for k, t in enumerate(toks)]
        srt_path = write_ass(ws, job.out / "captions.ass", job.W, job.H, cap)
        job.log("   captions: locked style ke mutabiq (ALL CAPS + highlight)")
    elif job.spec.get("subtitles", cfg["video"]["subtitles"]):
        srt_path = job.out / "subtitles.srt"
        srt_path.write_text("".join(f"{i}\n{_srt_t(a)} --> {_srt_t(b)}\n{w}\n\n" for i, (a, b, w) in enumerate(srt, 1)))
    music = media.music_bed(ROOT / cfg["music"]["folder"], t, job.work / "music_bed.wav", job.id, job.work)
    if not music:
        job.log("   ⚠ assets/music khali hai — video bina music ke")
    sfx_path = None
    rates = _profile(job).get("sfx") or {}
    if rates and sum(rates.values()) > 0.02:
        ev = sfx.plan_events(cut_ev, clip_ev, rates, job.id)
        sfx_path = sfx.render(ev, t, ROOT / "assets" / "sfx", job.work / "sfx_track.wav", job.id, cfg["video"].get("sfx_gain_db", -6))
        job.log(f"   sound effects: {len(ev)} (competitor rates {rates})")
    final = media.final_mix(full, music, job.out / f"{job.id}_{tag}.mp4", cfg, job.W, srt_path, job.out / "stems", sfx_path)
    script["placements"], script["section_starts"], script["runtime"] = placements, sec_starts, t
    script["montage_end"] = sec_starts[1][1] if len(sec_starts) > 1 else 0
    job.j("script.json", script)
    md = render_markdown(script, placements)  # clip log with ACTUAL video positions
    (job.out / "script.md").write_text(md)
    packaging.to_docx(md, job.out / "script.docx")
    with open(job.out / "clip_log.csv", "w", newline="") as f:
        rows = clip_log_rows(script, placements)
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    job.log(f"   final video {fmt(t)} → {final.name}")


def stage_package(job, cfg, ts, llm, **_):
    script = job.j("script.json")
    md = (job.out / "script.md").read_text()
    pk = packaging.make_packaging(llm, md)
    pk["chapters"] = packaging.chapters([(a, b) for a, b in script["section_starts"]])
    c1 = script["clips"][next(x["ref"] for x in script["sections"][0]["segments"] if x["type"] == "clip")]
    fr = media.grab_frame(srcfile(job, c1["src"]), c1.get("cut_start", c1["start"]) + 1.0, job.work / "thumb_frame.jpg")
    pk.setdefault("titles", []); pk.setdefault("tags", []); pk.setdefault("description", "")
    pk["thumbnail_texts"] = pk.get("thumbnail_texts") or [script["title"]]
    overlays.thumbnail(fr, pk["thumbnail_texts"][0], job.out / "thumbnail.jpg", ROOT / cfg["paths"]["fonts"])
    (job.out / "packaging.json").write_text(json.dumps(pk, indent=2, ensure_ascii=False))
    txt = ["# TITLES", *[f"- {x}" for x in pk["titles"]], "", "# DESCRIPTION", pk["description"], "",
           "# CHAPTERS", pk["chapters"], "", "# TAGS", ", ".join(pk["tags"]), "", "# THUMBNAIL TEXT",
           *[f"- {x}" for x in pk["thumbnail_texts"]]]
    (job.out / "packaging.md").write_text("\n".join(txt))
    (job.out / "project.json").write_text(json.dumps(script, indent=2, ensure_ascii=False))
    qa = job.work / "qa_report.json"
    if qa.exists():
        (job.out / "qa_report.json").write_text(qa.read_text())


def _chunk_words(ws, n=6):
    for i in range(0, len(ws), n):
        grp = ws[i:i + n]
        yield " ".join(w for w, _, _ in grp), grp[0][1], grp[-1][2]


def _srt_t(s):
    h, r = divmod(s, 3600)
    m, r = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(r):02d},{int((r % 1) * 1000):03d}"
