"""Stage A (plan) + Stage B (write) + render to master-prompt layout."""
import json
import re

from .config import ROOT, master_prompt_text
from .transcript import fmt

CARD_KINDS = ["CONFIRMED", "ALLEGED", "RUMOR", "SPECULATION", "CLAIM", "QUOTE", "DATE", "NONE"]


INPUTS_REF = "(the full inputs — main rumor + both transcripts — are in the system message under INPUTS)"


def system_prompt(cfg, job=None, transcripts=None):
    """Same prefix for every writer call (master prompt + inputs) so the provider's prompt cache hits."""
    adapter = (ROOT / "prompts" / "pipeline_adapter.md").read_text()
    s = adapter.replace("{MASTER_PROMPT}", master_prompt_text(cfg))
    if job is not None and transcripts is not None:
        s += "\n\nINPUTS\n" + inputs_block(job, transcripts)
    return s


def inputs_block(job, transcripts):
    parts = [f"MAIN RUMOR / IDEA (central storyline, highest priority):\n{job['rumor']}\n"]
    for t in transcripts:
        link = job.get(f"link{t.src}", "")
        parts.append(f"=== TRANSCRIPT {t.src} (source video: {link}) ===\n{t.for_prompt()}\n")
    return "\n".join(parts)


def words(text):
    return len(re.findall(r"\b[\w'’-]+\b", text))


# ---------------------------------------------------------------- Stage A
PLAN_TASK = """TASK — STAGE A: DOCUMENTARY PLAN

Build the full plan for the 17–20 minute documentary around the main rumor/idea. Sections should progress through revelations, contradictions and consequences (master prompt Sections 2, 5, 8). Distribute ALL usable original voice clips you can find across the montage and the body (Section 4: clips throughout, not only the opening).

Return JSON:
{{
  "working_title": "string",
  "core_angle": "one sentence: the storyline the whole video serves",
  "montage": [  // 2–4 clips, strongest first, strongest statement / open question last
    {{"src": 1, "lines": "L12-L13", "why": "why it opens the video"}}
  ],
  "sections": [  // body sections, in story order
    {{
      "id": "S1",
      "heading": "short internal heading",
      "purpose": "what this section reveals and how it moves the rumor forward",
      "target_words": 300,
      "clips": [
        {{"src": 2, "lines": "L40-L41", "label": "INTRO HOOK | MID-STORY REVEAL | TENSION PEAK | CONTRADICTION REVEAL | FINAL CONFIRMATION | PAUSE → PLAY CLIP", "why": "why here"}}
      ],
      "facts": [{{"claim": "...", "status": "confirmed | alleged | rumor | speculation | opinion", "basis": "T1:L5-L7 or RUMOR"}}]
    }}
  ]
}}
Rules: section target_words must sum to {target} (allowed {lo}–{hi}). No clip range may be used twice. Clip ranges must be real person speech, never narrator lines.

INPUTS
{inputs}
"""


def make_plan(llm, cfg, job, transcripts, log):
    sc = cfg["script"]
    user = PLAN_TASK.format(target=sc["target_words"], lo=sc["min_words"], hi=sc["max_words"],
                            inputs=INPUTS_REF)
    sysm = system_prompt(cfg, job, transcripts)
    for attempt in range(3):
        plan = llm.json("writer", sysm, user)
        errs = validate_plan(plan, transcripts, cfg)
        if not errs:
            return plan
        log(f"   plan validation ({len(errs)} issues) → re-plan: {errs[:3]}")
        user += "\n\nYOUR PREVIOUS PLAN HAD THESE ERRORS, FIX THEM:\n- " + "\n- ".join(errs) + \
                "\n\nPREVIOUS PLAN:\n" + json.dumps(plan)[:12000]
    raise RuntimeError("Plan 3 attempts ke baad bhi valid nahi: " + "; ".join(errs))


def _tmap(transcripts):
    return {t.src: t for t in transcripts}


def validate_plan(plan, transcripts, cfg):
    sc, tm, errs, seen = cfg["script"], _tmap(transcripts), [], set()
    m = plan.get("montage", [])
    lo, hi = sc["montage_clips"]
    if not (lo <= len(m) <= hi):
        errs.append(f"montage must have {lo}-{hi} clips, has {len(m)}")
    all_clips = [("montage", c) for c in m] + [(s.get("id"), c) for s in plan.get("sections", []) for c in s.get("clips", [])]
    for where, c in all_clips:
        try:
            t = tm[int(c["src"])]
            st, en, _, ids = t.span(c["lines"])
        except Exception as e:
            errs.append(f"{where}: bad clip ref {c}: {e}")
            continue
        key = (int(c["src"]), tuple(ids))
        if key in seen:
            errs.append(f"{where}: clip T{c['src']} {c['lines']} used twice")
        seen.add(key)
        dur = en - st
        lo_s, hi_s = sc["montage_clip_seconds"] if where == "montage" else sc["body_clip_seconds"]
        tol = sc["clip_tolerance_seconds"]
        if not (lo_s - tol <= dur <= hi_s + tol):
            kind = "opening-montage clips must be 3–8s (Section 3)" if where == "montage" else "body clips must be 5–10s (Section 4)"
            errs.append(f"{where}: clip T{c['src']} {c['lines']} is {dur:.1f}s — {kind}; choose a different line range")
    mclip_s = 0.0
    for c in m:
        try:
            a, b, _, _ = tm[int(c["src"])].span(c["lines"])
            mclip_s += b - a
        except Exception:
            pass
    if mclip_s > sc["montage_seconds"][1]:
        errs.append(f"montage clips total {mclip_s:.0f}s — the whole montage must fit in 30–45s (Section 3)")
    secs = plan.get("sections", [])
    # target_words sirf planning hai; total range se bahar ho to yahin proportionally scale (asal word count write + QA enforce karte hain)
    tot = sum(max(0, int(s.get("target_words", 0) or 0)) for s in secs)
    if secs and not (sc["min_words"] <= tot <= sc["max_words"]):
        goal = sc["target_words"]
        for s in secs:
            w = int(s.get("target_words", 0) or 0)
            s["target_words"] = max(120, round((w if tot else goal / len(secs)) * goal / (tot or goal)))
    return errs


def register_clips(plan, transcripts):
    """Assign C1..Cn; copy EXACT words + real timestamps from transcript."""
    tm, clips, n = _tmap(transcripts), {}, 0

    def add(c, label, section, montage):
        nonlocal n
        n += 1
        t = tm[int(c["src"])]
        st, en, text, ids = t.span(c["lines"])
        cid = f"C{n}"
        clips[cid] = dict(id=cid, src=int(c["src"]), lines=c["lines"], ids=ids, start=st, end=en,
                          quote=text, label=label, why=c.get("why", ""), montage=montage, section=section)
        return cid

    for i, c in enumerate(plan["montage"], 1):
        add(c, f"OPENING MONTAGE – CLIP {i}", "S0", True)
    for s in plan["sections"]:
        s["clip_ids"] = [add(c, (c.get("label") or "PAUSE → PLAY CLIP").split("|")[0].strip(), s["id"], False)
                         for c in s.get("clips", [])]
    return clips


# ---------------------------------------------------------------- Stage B
SEG_SCHEMA = """Return JSON:
{
  "segments": [
    {"type": "narration", "text": "spoken voiceover text",
     "broll": [{"src": 1, "lines": "L30-L33"}],
     "card": {"kind": "CONFIRMED | ALLEGED | RUMOR | SPECULATION | CLAIM | QUOTE | DATE | NONE", "text": "max 8 words on screen"}},
    {"type": "clip", "ref": "C3"}
  ]
}
- "text" is pure voiceover: no stage directions, no markers, no headings, no quotation of the clip words.
- Put each clip where it belongs; the narration right before a clip must lead into it naturally (master prompt Section 4); the narration after it continues the story without repeating the clip.
- Split narration into blocks at natural paragraph breaks; give each block its b-roll ranges.
- Use "card" only when it helps the viewer separate confirmed fact from allegation/rumor or shows a date/claim; otherwise kind NONE."""

MONTAGE_TASK = """TASK — STAGE B: WRITE THE OPENING MONTAGE (first 30–45 seconds, master prompt Section 3)

Clips to use, in this order: {order}
Clip words (exact, for your context only — do not repeat them in narration):
{clipinfo}

Start IMMEDIATELY with the first clip (the first segment must be a clip, no narration before it). Use short narration between clips only when necessary (master prompt Section 3). After the last clip, write ONE narration block that transitions straight into the central rumor with direct documentary narration — no greeting, no "in this video", no announcing what is coming.
TIMING (hard): the clips above total {clip_s:.0f}s. The montage window (clips + bridge lines + transition block) must total 30–45 seconds at ~{wps} spoken words per second, so ALL montage narration together must be between {wmin} and {wmax} words.

""" + SEG_SCHEMA.replace("{", "{{").replace("}", "}}") + """

PLAN CONTEXT: {angle}

INPUTS
{inputs}
"""

SECTION_TASK = """TASK — STAGE B: WRITE SECTION {sid} of the documentary.

Section heading (internal): {heading}
Purpose: {purpose}
TARGET LENGTH: about {target} spoken words of narration, so the full video lands between {lo} and {hi} words (master prompt Section 5).
Clips that MUST appear in this section (each exactly once): {clips}
Clip words (exact, context only):
{clipinfo}
Facts for this section and their status (keep the status honest in the narration):
{facts}

STORY SO FAR (last part of previous section's narration, for continuity — do not repeat it):
{prev}

FULL PLAN (for callbacks and to avoid repeating other sections):
{outline}
{extra}
""" + SEG_SCHEMA.replace("{", "{{").replace("}", "}}") + """

INPUTS
{inputs}
"""


def _clipinfo(clips, ids):
    return "\n".join(f"{c}: T{clips[c]['src']} [{fmt(clips[c]['start'])}] \"{clips[c]['quote']}\"" for c in ids) or "(none)"


def outline_text(plan):
    return "\n".join(f"{s['id']} {s['heading']} — {s['purpose']} ({s['target_words']}w)" for s in plan["sections"])


def write_montage(llm, cfg, job, transcripts, plan, clips):
    ids = [c for c in clips if clips[c]["montage"]]
    user = MONTAGE_TASK.format(order=", ".join(ids), clipinfo=_clipinfo(clips, ids),
                               angle=plan.get("core_angle", ""), inputs=INPUTS_REF,
                               **montage_budget(cfg, clips, ids))
    return llm.json("writer", system_prompt(cfg, job, transcripts), user)["segments"]


def montage_budget(cfg, clips, ids):
    sc = cfg["script"]
    clip_s = sum(clips[i]["end"] - clips[i]["start"] for i in ids)
    wps = sc["words_per_second"]
    lo, hi = sc["montage_seconds"]
    return dict(clip_s=clip_s, wps=wps, wmin=max(15, round((lo - clip_s) * wps)), wmax=max(25, round((hi - clip_s) * wps)))


def write_section(llm, cfg, job, transcripts, plan, clips, sec, prev_text, extra=""):
    sc = cfg["script"]
    user = SECTION_TASK.format(
        sid=sec["id"], heading=sec["heading"], purpose=sec["purpose"], target=sec["target_words"],
        lo=sc["min_words"], hi=sc["max_words"], clips=", ".join(sec["clip_ids"]) or "(none)",
        clipinfo=_clipinfo(clips, sec["clip_ids"]),
        facts="\n".join(f"- [{f.get('status')}] {f.get('claim')} ({f.get('basis')})" for f in sec.get("facts", [])) or "-",
        prev=prev_text[-1500:] or "(this is the first body section; the montage transition just ended)",
        outline=outline_text(plan), extra=extra, inputs=INPUTS_REF)
    return llm.json("writer", system_prompt(cfg, job, transcripts), user)["segments"]


def clean_segments(segs, allowed_refs, transcripts):
    tm, out, used = _tmap(transcripts), [], set()
    for s in segs:
        if s.get("type") == "clip":
            r = str(s.get("ref", "")).upper()
            if r in allowed_refs and r not in used:
                used.add(r)
                out.append({"type": "clip", "ref": r})
        elif s.get("type") == "narration" and s.get("text", "").strip():
            br = []
            for b in s.get("broll", []) or []:
                try:
                    tm[int(b["src"])].span(b["lines"])
                    br.append({"src": int(b["src"]), "lines": b["lines"]})
                except Exception:
                    pass
            card = s.get("card") or {}
            if str(card.get("kind", "NONE")).upper() not in CARD_KINDS or str(card.get("kind")).upper() == "NONE":
                card = None
            text = re.sub(r"\[.*?PLAY CLIP.*?\]", "", s["text"]).strip()
            out.append({"type": "narration", "text": text, "broll": br, "card": card})
    missing = [r for r in allowed_refs if r not in used]
    return out, missing


def narration_words(script):
    return sum(words(s["text"]) for sec in script["sections"] for s in sec["segments"] if s["type"] == "narration")


def section_words(sec):
    return sum(words(s["text"]) for s in sec["segments"] if s["type"] == "narration")


# ---------------------------------------------------------------- render
def render_markdown(script, timings=None):
    """timings: {clip_id: placement_seconds} from final assembly (actual), else estimates."""
    clips, wps = script["clips"], script.get("wps", 2.4)
    t, est = 0.0, {}
    lines = [f"# {script['title']}", "",
             f"*Narration words: {narration_words(script)} · Estimated runtime: {fmt(script_seconds(script))}*", ""]
    for sec in script["sections"]:
        head = (f"OPENING HIGH-IMPACT VOICE-CLIP MONTAGE (0:00–{fmt(montage_seconds(script, timings))})"
                if sec["id"] == "S0" else sec["heading"].upper())
        lines += [f"## {head}", ""]
        for s in sec["segments"]:
            if s["type"] == "narration":
                lines += [s["text"], ""]
                t += words(s["text"]) / wps
            else:
                c = clips[s["ref"]]
                est[c["id"]] = t
                place = (timings or {}).get(c["id"], t)
                kind = "actual" if timings else "estimated"
                lines += [
                    f"[PAUSE → PLAY CLIP]  **{c['label']}**",
                    "",
                    f"> **VOICE CLIP CALLOUT — {c['id']}**  ",
                    f"> Source: Transcript {c['src']} · original transcript timestamp {fmt(c['start'])} ({c['lines']}){cut_note(c)}  ",
                    f"> Exact clip: \"{c['quote'].strip(chr(34) + '“”')}\"  ",
                    f"> Placement: **{c['label']}** · video position ~{fmt(place)} ({kind})  ",
                    f"> Why here: {c['why']}  ",
                    f"> Suggested duration: {clip_len(c):.0f}s",
                    "",
                ]
                t += clip_len(c)
    script["_est_place"] = est
    lines += ["---", "", "# CLIP LOG FOR EDITORS", ""]
    lines += clip_log_md(script, timings)
    return "\n".join(lines)


def clip_log_rows(script, timings=None):
    est = script.get("_est_place", {})
    rows = []
    order = [s["ref"] for sec in script["sections"] for s in sec["segments"] if s["type"] == "clip"]
    for cid in order:
        c = script["clips"][cid]
        place = (timings or {}).get(cid, est.get(cid, 0))
        rows.append(dict(clip=cid, montage=c["montage"], source=f"Transcript {c['src']}",
                         quote=c["quote"], placement=c["label"],
                         source_timestamp=f"{fmt(c['start'])} ({c['lines']}){cut_note(c)}",
                         video_position=fmt(place) + (" (actual)" if timings else " (estimated)"),
                         length=f"{clip_len(c):.0f}s", purpose=c["why"]))
    return rows


def clip_log_md(script, timings=None):
    rows = clip_log_rows(script, timings)
    out = []
    for title, flag in (("### Opening montage clips", True), ("### Body clips", False)):
        out += [title, "", "| # | Source | Exact quote | Placement | Source timestamp | Video position | Length | Purpose |",
                "|---|---|---|---|---|---|---|---|"]
        for r in rows:
            if r["montage"] == flag:
                q = r["quote"].strip('"“”').replace("|", "/")
                out.append(f"| {r['clip']} | {r['source']} | \"{q}\" | **{r['placement']}** | {r['source_timestamp']} | {r['video_position']} | {r['length']} | {r['purpose']} |")
        out.append("")
    return out


def clip_len(c):
    return c.get("cut_end", c["end"]) - c.get("cut_start", c["start"])


def cut_note(c):
    """Original start comes from the transcript. Cut points are labelled with where they came from."""
    if "cut_start" in c:
        src = "word-level audio match" if c.get("edge_source") == "whisper" else "transcript line bounds"
        return f" · cut {fmt(c['cut_start'])}–{fmt(c['cut_end'])} ({src})"
    return " · end = next transcript line (estimated)"


def montage_seconds(script, timings=None):
    if timings and script.get("montage_end"):
        return script["montage_end"]
    s0 = script["sections"][0]["segments"]
    return sum(clip_len(script["clips"][x["ref"]]) if x["type"] == "clip" else words(x["text"]) / script.get("wps", 2.4)
               for x in s0)


def script_seconds(script):
    wps = script.get("wps", 2.4)
    tot = narration_words(script) / wps
    for sec in script["sections"]:
        for s in sec["segments"]:
            if s["type"] == "clip":
                c = script["clips"][s["ref"]]
                tot += c["end"] - c["start"]
    return tot
