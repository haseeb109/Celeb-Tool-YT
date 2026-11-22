"""Phase 1 (deterministic checks) + Phase 2 (independent model audit) + auto-fix loop."""
import json
import re

from rapidfuzz import fuzz

from .config import master_prompt_text
from .script_engine import (clean_segments, inputs_block, narration_words, render_markdown,
                            section_words, write_section, words)

BANNED = [  # master prompt Section 7 — exact list. "Slightly reworded" variants → fuzzy match below.
    "let's connect the dots", "but here's what nobody is connecting", "hold on, because this gets even crazier",
    "what happened next changed everything", "before we get into that", "there's something much bigger going on here",
    "and that's where things get interesting", "but the real question is", "you won't believe what happened next",
    "now, here's where things take a dark turn",
]
GREETINGS = ["welcome back", "hey guys", "hello everyone", "in this video", "in today's video"]  # Sec 3: no greetings / narrator intro


def phase1(script, cfg):
    sc, issues = cfg["script"], []
    total = narration_words(script)
    if total < sc["min_words"]:
        issues.append(dict(severity="major", section="ALL", rule="Section 5 length",
                           problem=f"narration is {total} words, below {sc['min_words']}", fix="expand"))
    if total > sc["max_words"]:
        issues.append(dict(severity="major", section="ALL", rule="Section 5 length",
                           problem=f"narration is {total} words, above {sc['max_words']}", fix="trim"))
    s0 = script["sections"][0]["segments"]
    if not s0 or s0[0]["type"] != "clip":
        issues.append(dict(severity="major", section="S0", rule="Section 3",
                           problem="video does not open immediately with a voice clip", fix="start with clip"))
    mclips = [s for s in s0 if s["type"] == "clip"]
    lo, hi = sc["montage_clips"]
    if not lo <= len(mclips) <= hi:
        issues.append(dict(severity="major", section="S0", rule="Section 3",
                           problem=f"montage has {len(mclips)} clips", fix=f"{lo}-{hi} clips"))
    from .script_engine import montage_seconds
    mdur = montage_seconds(script)
    if not (sc["montage_seconds"][0] <= mdur <= sc["montage_seconds"][1]):
        clip_s = sum(script["clips"][c["ref"]]["end"] - script["clips"][c["ref"]]["start"] for c in mclips)
        need = round((35 - clip_s) * script["wps"])
        issues.append(dict(severity="major", section="S0", rule="Section 3 (30–45s montage)",
                           problem=f"montage window is ~{mdur:.0f}s, must be 30–45s",
                           fix=f"make ALL montage narration together about {need} words"))
    used = [s["ref"] for sec in script["sections"] for s in sec["segments"] if s["type"] == "clip"]
    for cid in script["clips"]:
        if cid not in used:
            issues.append(dict(severity="minor", section=script["clips"][cid]["section"], rule="Section 9",
                               problem=f"{cid} planned but not placed (dropped from log)", fix=""))
    for sec in script["sections"]:
        for s in sec["segments"]:
            if s["type"] != "narration":
                continue
            low = s["text"].lower()
            for b in BANNED + (GREETINGS if sec["id"] in ("S0", "S1") else []):
                if b in low or fuzz.partial_ratio(b, low) >= 88:
                    issues.append(dict(severity="major", section=sec["id"], rule="Section 7 banned phrase",
                                       problem=f"contains generic phrase like \"{b}\"", fix="rewrite that sentence with concrete information"))
                    break
    return issues


AUDIT_TASK = """You are the independent QA auditor. Audit the rendered documentary script below against EVERY rule of the locked master prompt (included in your system message), and against the inputs.

Check especially:
1. Does the main rumor/idea control the narrative start to finish? Any section drifting off-topic or into unrelated controversies?
2. Is any rumor, allegation or speculation narrated as established fact? Any invented quote, number, date, source or event that is not in the inputs?
3. Generic AI phrases / filler / repetitive suspense lines (Section 7), paragraphs that add nothing.
4. Montage: opens directly with a clip, no greeting, transitions straight into the rumor.
5. Narration lead-ins to clips, no repeating the clip words afterwards, continuity between sections, repeated information.
6. Tone: dark, direct investigative documentary — not news report, not generic YouTube commentary.
Clip words and timestamps are copied mechanically from the transcripts — do not flag them as altered.

Return JSON:
{{"pass": true/false,
  "issues": [{{"severity": "major|minor", "section": "S0..Sn", "rule": "which master prompt section", "problem": "specific, quote the offending text", "fix": "specific instruction"}}]}}
"major" = breaks a master prompt rule or misstates facts. Style nitpicks are "minor".

SCRIPT
{script}

INPUTS
{inputs}
"""


def phase2(llm, cfg, job, transcripts, script):
    sysm = ("You are a strict script compliance auditor.\n\n=== LOCKED MASTER PROMPT ===\n" + master_prompt_text(cfg)
            + "\n\nINPUTS\n" + inputs_block(job, transcripts))
    md = render_markdown(script)
    md_numbered = md
    for sec in script["sections"]:  # tag headings with section ids so the auditor can point at them
        h = sec["heading"].upper()
        md_numbered = md_numbered.replace(f"## {h}", f"## [{sec['id']}] {h}", 1)
    md_numbered = md_numbered.replace("## OPENING HIGH-IMPACT", "## [S0] OPENING HIGH-IMPACT", 1)
    r = llm.json("auditor", sysm, AUDIT_TASK.format(script=md_numbered.split("# CLIP LOG")[0],
                                                     inputs="(in the system message under INPUTS)"), temperature=0.2)
    return r.get("issues", [])


def run_qa(llm, cfg, job, transcripts, script, plan, log):
    report = []
    for rnd in range(1, cfg["script"]["qa_max_rounds"] + 1):
        issues = phase1(script, cfg)
        majors1 = [i for i in issues if i["severity"] == "major"]
        if not majors1:
            log(f"   QA round {rnd}: phase 1 clean → phase 2 audit ({cfg['llm']['auditor_model']})")
            issues += phase2(llm, cfg, job, transcripts, script)
        majors = [i for i in issues if i["severity"] == "major"]
        report.append({"round": rnd, "words": narration_words(script), "issues": issues})
        log(f"   QA round {rnd}: {len(majors)} major, {len(issues) - len(majors)} minor, {narration_words(script)} words")
        if not majors:
            return report, True
        fix_issues(llm, cfg, job, transcripts, script, plan, majors, log)
    final = phase1(script, cfg)
    report.append({"round": "final", "words": narration_words(script), "issues": final})
    return report, not [i for i in final if i["severity"] == "major"]


def fix_issues(llm, cfg, job, transcripts, script, plan, majors, log):
    sc = cfg["script"]
    by_sec = {}
    total = narration_words(script)
    for i in majors:
        if i["section"] == "ALL":  # length problem → spread across body sections
            body = [s for s in script["sections"] if s["id"] != "S0"]
            goal = sc["target_words"]
            for s in body:
                cur = section_words(s)
                want = max(120, round(cur * goal / max(total, 1)))
                if abs(want - cur) > 30:
                    by_sec.setdefault(s["id"], []).append(
                        dict(problem=f"section is {cur} words; total video is {total}", fix=f"rewrite this section to {want} words"))
                    s["_target"] = want
        else:
            by_sec.setdefault(i["section"], []).append(i)
    plan_secs = {s["id"]: s for s in plan["sections"]}
    prev_text = {}
    for idx, sec in enumerate(script["sections"]):
        prev_text[sec["id"]] = " ".join(x["text"] for x in script["sections"][idx - 1]["segments"]
                                        if x["type"] == "narration") if idx > 0 else ""

    def fix_one(sec):
        probs = "\n".join(f"- {p['problem']} → FIX: {p['fix']}" for p in by_sec[sec["id"]])
        current = json.dumps(sec["segments"], ensure_ascii=False)
        extra = f"\nREVISION: this section already exists. Rewrite it fixing these QA problems; keep everything that was fine.\n{probs}\nCURRENT VERSION:\n{current}\n"
        prev = prev_text[sec["id"]]
        log(f"   fixing {sec['id']} ({len(by_sec[sec['id']])} problems)")
        if sec["id"] == "S0":
            from .script_engine import INPUTS_REF, MONTAGE_TASK, _clipinfo, montage_budget, system_prompt
            ids = [s["ref"] for s in sec["segments"] if s["type"] == "clip"] or [c for c in script["clips"] if script["clips"][c]["montage"]]
            user = MONTAGE_TASK.format(order=", ".join(ids), clipinfo=_clipinfo(script["clips"], ids),
                                       angle=plan.get("core_angle", ""), inputs=INPUTS_REF,
                                       **montage_budget(cfg, script["clips"], ids)) + extra
            segs = llm.json("writer", system_prompt(cfg, job, transcripts), user)["segments"]
            allowed = ids
        else:
            ps = dict(plan_secs[sec["id"]])
            ps["target_words"] = sec.pop("_target", ps["target_words"])
            segs = write_section(llm, cfg, job, transcripts, plan, script["clips"], ps, prev, extra)
            allowed = ps["clip_ids"]
        return sec, segs, allowed

    from concurrent.futures import ThreadPoolExecutor
    todo = [sec for sec in script["sections"] if sec["id"] in by_sec]
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(fix_one, todo))
    for sec, segs, allowed in results:
        new, missing = clean_segments(segs, allowed, transcripts)
        if new:
            sec["segments"] = new
