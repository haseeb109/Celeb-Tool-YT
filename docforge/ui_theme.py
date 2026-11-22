"""Ice Light (frosted glass) theme for the Gradio GUI + dark mode. Pure CSS + tiny JS toggle."""
import html
import json

FONTS = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;700&family=JetBrains+Mono:wght@400;500&display=swap"

CSS = """
@import url('""" + FONTS + """');

/* ---------- tokens: Ice Light (default) ---------- */
:root, .gradio-container {
  --ice-bg: #E9EEF6; --ice-text: #0F172A; --ice-sub: #475569;
  --ice-acc: #2563EB; --ice-acc2: #06B6D4; --ice-onacc: #FFFFFF;
  --ice-panel: rgba(255,255,255,0.58); --ice-line: rgba(15,23,42,0.10); --ice-hover: rgba(15,23,42,0.05);
  --ice-shadow: 0 8px 32px rgba(15,23,42,0.10), inset 0 1px 0 rgba(255,255,255,0.75);
  --ice-orb1: #93C5FD; --ice-orb2: #A5F3FC; --ice-orb3: #C4B5FD; --ice-orb-op: .55;
}
.dark, .dark .gradio-container {
  --ice-bg: #0A1020; --ice-text: #EEF2FF; --ice-sub: #A5B0CC;
  --ice-acc: #7CA4FF; --ice-acc2: #5EE6D0; --ice-onacc: #0A1020;
  --ice-panel: rgba(255,255,255,0.06); --ice-line: rgba(255,255,255,0.12); --ice-hover: rgba(255,255,255,0.07);
  --ice-shadow: 0 8px 32px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.08);
  --ice-orb1: #1D4ED8; --ice-orb2: #0E7490; --ice-orb3: #6D28D9; --ice-orb-op: .40;
}

/* map onto Gradio's own variables so every component follows */
.gradio-container, .dark .gradio-container {
  --body-background-fill: transparent; --background-fill-primary: transparent; --background-fill-secondary: var(--ice-hover);
  --block-background-fill: var(--ice-panel); --block-border-color: var(--ice-line); --block-radius: 20px;
  --block-label-background-fill: transparent; --block-title-text-color: var(--ice-sub); --block-label-text-color: var(--ice-sub);
  --body-text-color: var(--ice-text); --body-text-color-subdued: var(--ice-sub);
  --border-color-primary: var(--ice-line); --border-color-accent: var(--ice-acc);
  --input-background-fill: var(--ice-hover); --input-border-color: var(--ice-line); --input-radius: 12px;
  --input-background-fill-focus: var(--ice-panel); --input-border-color-focus: var(--ice-acc);
  --button-primary-background-fill: var(--ice-acc); --button-primary-background-fill-hover: var(--ice-acc);
  --button-primary-text-color: var(--ice-onacc); --button-primary-border-color: var(--ice-acc);
  --button-secondary-background-fill: var(--ice-hover); --button-secondary-background-fill-hover: var(--ice-hover);
  --button-secondary-text-color: var(--ice-text); --button-secondary-border-color: var(--ice-line);
  --button-large-radius: 999px; --button-small-radius: 999px; --button-medium-radius: 999px;
  --color-accent: var(--ice-acc); --color-accent-soft: color-mix(in srgb, var(--ice-acc) 15%, transparent);
  --table-even-background-fill: transparent; --table-odd-background-fill: var(--ice-hover);
  --code-background-fill: var(--ice-hover);
  --font: 'Inter', system-ui, sans-serif; --font-mono: 'JetBrains Mono', ui-monospace, monospace;
}

/* ---------- page + moving light orbs ---------- */
body, gradio-app { background: var(--ice-bg) !important; color: var(--ice-text); transition: background .4s ease; }
body::before, body::after, .gradio-container::before {
  content: ""; position: fixed; z-index: 0; border-radius: 50%; filter: blur(110px); opacity: var(--ice-orb-op); pointer-events: none;
}
body::before { width: 560px; height: 560px; left: -120px; top: -140px; background: var(--ice-orb1); animation: iceDrift0 16s ease-in-out infinite; }
body::after  { width: 500px; height: 500px; right: -120px; top: 35%; background: var(--ice-orb2); animation: iceDrift1 19s ease-in-out infinite; }
.gradio-container::before { width: 460px; height: 460px; left: 35%; bottom: -200px; background: var(--ice-orb3); animation: iceDrift2 22s ease-in-out infinite; }
@keyframes iceDrift0 { 50% { transform: translate(80px, 60px) scale(1.1); } }
@keyframes iceDrift1 { 50% { transform: translate(-90px, 40px) scale(.95); } }
@keyframes iceDrift2 { 50% { transform: translate(60px, -70px) scale(1.08); } }
.gradio-container { position: relative; z-index: 1; max-width: 1240px !important; margin: 0 auto !important; font-family: var(--font) !important; }
.gradio-container > * { position: relative; z-index: 1; }

/* ---------- glass panels ---------- */
.block, .form, .tabitem, .gr-group, fieldset {
  backdrop-filter: blur(22px) saturate(140%); -webkit-backdrop-filter: blur(22px) saturate(140%);
}
.block { box-shadow: var(--ice-shadow) !important; border: 1px solid var(--ice-line) !important; border-radius: 20px !important;
         animation: iceRise .45s ease both; }
.form > .block, .block .block { box-shadow: none !important; animation: none; }
@keyframes iceRise { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
h1, h2, h3 { font-family: 'Space Grotesk', var(--font) !important; letter-spacing: -0.01em; color: var(--ice-text) !important; }
.prose, .md, label, span { color: inherit; }

/* ---------- tabs: glass pill bar ---------- */
.tab-wrapper, .tab-nav, div[role="tablist"] {
  background: var(--ice-panel) !important; border: 1px solid var(--ice-line) !important; border-radius: 999px !important;
  padding: 6px !important; gap: 4px; box-shadow: var(--ice-shadow); backdrop-filter: blur(22px); -webkit-backdrop-filter: blur(22px);
}
button[role="tab"] { border: none !important; border-radius: 999px !important; padding: 10px 16px !important; color: var(--ice-sub) !important;
  font-weight: 500 !important; transition: color .15s ease, background .2s ease, box-shadow .2s ease !important; background: transparent !important; }
button[role="tab"]:hover { color: var(--ice-text) !important; background: var(--ice-hover) !important; }
button[role="tab"][aria-selected="true"], button[role="tab"].selected {
  color: var(--ice-text) !important; background: color-mix(in srgb, var(--ice-acc) 16%, transparent) !important;
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--ice-acc) 40%, transparent) !important; }
button[role="tab"][aria-selected="true"]::after, button[role="tab"].selected::after { display: none !important; }

/* ---------- buttons: lift, press, glow ---------- */
button.lg, button.md, button.sm, .gr-button, button.primary, button.secondary {
  transition: transform .15s ease, box-shadow .2s ease, filter .2s ease, border-color .2s ease !important; font-weight: 600 !important;
}
button.primary:hover { transform: translateY(-1px); box-shadow: 0 8px 24px color-mix(in srgb, var(--ice-acc) 40%, transparent); }
button.secondary:hover { transform: translateY(-1px); border-color: var(--ice-acc) !important; }
button.primary:active, button.secondary:active { transform: scale(.97); }
button.stop { border-radius: 999px !important; }

/* markdown headings/notes: plain text, no glass box */
.block:has(.prose):not(:has(input, textarea, select, button, table, audio, video)) {
  background: transparent !important; border: none !important; box-shadow: none !important;
  backdrop-filter: none !important; -webkit-backdrop-filter: none !important; animation: none !important;
  overflow: visible !important; padding-left: 2px !important; }

/* ---------- header ---------- */
.ice-plain, .ice-plain > .block, #ice-actions, #ice-actions .block, #ice-head, #ice-head > .block {
  background: transparent !important; border: none !important; box-shadow: none !important;
  backdrop-filter: none !important; -webkit-backdrop-filter: none !important; padding: 0 !important; animation: none !important; }
#ice-head { align-items: center !important; flex-wrap: wrap !important; gap: 12px !important; }
#ice-actions { flex-wrap: nowrap !important; }
.ice-plain .prose:empty, .ice-plain:has(.prose:empty) { display: none; }
#ice-header { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; padding: 4px 2px 6px; }
#ice-header .brand { display: flex; align-items: center; gap: 12px; }
#ice-header .logo { width: 40px; height: 40px; border-radius: 12px; display: flex; align-items: center; justify-content: center;
  background: var(--ice-panel); border: 1px solid var(--ice-line); box-shadow: var(--ice-shadow); color: var(--ice-acc); }
#ice-header .name { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 20px; color: var(--ice-text); line-height: 1.1; }
#ice-header .tag { font-size: 12px; color: var(--ice-sub); }
.ice-chip { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--ice-sub); background: var(--ice-panel);
  border: 1px solid var(--ice-line); border-radius: 999px; padding: 7px 12px; backdrop-filter: blur(16px); white-space: nowrap; }
#ice-actions { gap: 10px !important; align-items: center !important; justify-content: flex-end; flex-wrap: wrap; }
#ice-actions > * { flex: 0 0 auto !important; min-width: 0 !important; }

/* update button: pulse + sheen + spinning icon */
#ice-update { position: relative; overflow: hidden; border-radius: 999px !important; padding: 0 18px !important; min-height: 42px;
  background: var(--ice-acc) !important; color: var(--ice-onacc) !important; border: 1px solid var(--ice-acc) !important;
  animation: icePulse 2.4s infinite; }
#ice-update::before { content: ""; position: absolute; top: 0; bottom: 0; width: 40%; left: -60%;
  background: linear-gradient(100deg, transparent, rgba(255,255,255,.55), transparent); animation: iceSheen 2.8s ease-in-out infinite; }
#ice-update:hover { transform: translateY(-1px); filter: brightness(1.07); }
#ice-update:active { transform: scale(.97); }
#ice-update.latest { animation: none; background: var(--ice-panel) !important; color: var(--ice-text) !important; border-color: var(--ice-line) !important; }
#ice-update.latest::before { display: none; }
@keyframes icePulse { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--ice-acc) 55%, transparent); }
  70% { box-shadow: 0 0 0 14px transparent; } 100% { box-shadow: 0 0 0 0 transparent; } }
@keyframes iceSheen { 0% { left: -60%; } 60%, 100% { left: 130%; } }
#ice-theme { border-radius: 999px !important; min-width: 42px !important; min-height: 42px; padding: 0 14px !important; }

/* ---------- toast (updated / messages) ---------- */
.ice-toast { animation: iceRise .5s ease both; background: var(--ice-panel); border: 1px solid var(--ice-line); border-radius: 18px;
  padding: 14px 18px; box-shadow: var(--ice-shadow); backdrop-filter: blur(22px); }
.ice-toast b { color: var(--ice-text); }
.ice-toast ul { margin: 8px 0 0; padding-left: 18px; color: var(--ice-sub); font-size: 13px; line-height: 1.6; }

/* ---------- queue cards ---------- */
.ice-queue { display: flex; flex-direction: column; gap: 12px; }
.ice-job { background: var(--ice-panel); border: 1px solid var(--ice-line); border-radius: 20px; padding: 16px 18px;
  box-shadow: var(--ice-shadow); backdrop-filter: blur(22px); animation: iceRise .45s ease both; transition: transform .2s ease, border-color .2s ease; }
.ice-job:hover { transform: translateY(-1px); border-color: color-mix(in srgb, var(--ice-acc) 45%, transparent); }
.ice-job .top { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.ice-job .title { font-weight: 600; font-size: 15px; color: var(--ice-text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ice-job .meta { font-size: 12px; color: var(--ice-sub); margin-top: 2px; }
.ice-badge { font-size: 12px; font-weight: 600; padding: 4px 10px; border-radius: 999px; border: 1px solid var(--ice-line); color: var(--ice-sub); white-space: nowrap; }
.ice-badge.running { background: var(--ice-acc); color: var(--ice-onacc); border-color: var(--ice-acc); }
.ice-badge.done { color: var(--ice-text); }
.ice-badge.failed { color: #DC2626; border-color: #DC262666; }
.ice-bar { margin-top: 12px; height: 8px; border-radius: 999px; background: var(--ice-line); overflow: hidden; }
.ice-bar > div { height: 100%; border-radius: 999px; background: var(--ice-acc); transition: width .6s ease; }
.ice-bar > div.live { background-image: linear-gradient(90deg, var(--ice-acc) 0, var(--ice-acc2) 50%, var(--ice-acc) 100%);
  background-size: 220px 100%; animation: iceShimmer 1.4s linear infinite; }
@keyframes iceShimmer { 0% { background-position: -220px 0; } 100% { background-position: 220px 0; } }
.ice-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; padding: 0; }
.ice-chips li { list-style: none; display: flex; align-items: center; gap: 6px; padding: 5px 10px; border-radius: 999px; font-size: 12px;
  border: 1px solid var(--ice-line); background: var(--ice-hover); color: var(--ice-sub); }
.ice-chips li.done { color: var(--ice-text); } .ice-chips li.done svg { color: var(--ice-acc); }
.ice-chips li.active { color: var(--ice-text); border-color: var(--ice-acc); background: color-mix(in srgb, var(--ice-acc) 16%, transparent); }
.ice-dot { width: 8px; height: 8px; border-radius: 99px; background: var(--ice-acc); animation: iceBlink 1s infinite; }
.ice-hollow { width: 8px; height: 8px; border-radius: 99px; border: 1.5px solid var(--ice-sub); box-sizing: border-box; }
@keyframes iceBlink { 50% { opacity: .3; } }
.ice-err { margin-top: 10px; font-size: 12px; color: #DC2626; font-family: 'JetBrains Mono', monospace; }
.ice-empty { text-align: center; color: var(--ice-sub); padding: 28px; border: 1px dashed var(--ice-line); border-radius: 20px; }

@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; transition: none !important; } }
"""

# theme: default light (Ice), remembered per browser
THEME_JS = """
() => {
  const t = (localStorage.getItem('celeb-theme') || 'light');
  document.body.classList.toggle('dark', t === 'dark');
  document.documentElement.classList.toggle('dark', t === 'dark');
  const b = document.querySelector('#ice-theme'); if (b) b.textContent = t === 'dark' ? '☀ Light' : '☾ Dark';
}
"""
TOGGLE_JS = """
() => {
  const dark = !document.body.classList.contains('dark');
  document.body.classList.toggle('dark', dark);
  document.documentElement.classList.toggle('dark', dark);
  localStorage.setItem('celeb-theme', dark ? 'dark' : 'light');
  const b = document.querySelector('#ice-theme'); if (b) b.textContent = dark ? '☀ Light' : '☾ Dark';
}
"""

LOGO = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M10 9l5 3-5 3z"/></svg>')
CHECK = ('<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" '
         'aria-hidden="true"><path d="M5 12l5 5L20 7"/></svg>')


def brand_html():
    return (f'<div id="ice-header"><div class="brand"><span class="logo">{LOGO}</span><div><div class="name">Celeb Tool YT</div>'
            f'<div class="tag">Dark documentary pipeline · master prompt locked</div></div></div></div>')


def chip_html(ver):
    return f'<div style="display:flex;justify-content:flex-end"><span class="ice-chip">{html.escape(ver["label"])} · {html.escape(ver.get("date") or "")}</span></div>'


def toast_html(title, items=None):
    li = "".join(f"<li>{html.escape(i)}</li>" for i in (items or [])[:8])
    return f'<div class="ice-toast"><b>{html.escape(title)}</b>' + (f"<ul>{li}</ul>" if li else "") + "</div>"


def queue_html(jobs, stages, labels):
    if not jobs:
        return '<div class="ice-empty">Queue khali hai — ➕ New Job se job add karo</div>'
    cards = []
    for j in jobs:
        st = j.get("status") or {}
        done = set(st.get("done", []))
        state = j["state"] or "pending"
        n = sum(1 for s in stages if s in done)
        pct = 100 if state == "done" else int(n / len(stages) * 100)
        cur = next((labels[i] for i, s in enumerate(stages) if s not in done), labels[-1])
        meta = {"running": f"{cur} · {n}/{len(stages)}", "done": "Done", "failed": f"Ruki: {cur}", "pending": "Queued"}.get(state, state)
        chips = []
        for i, s in enumerate(stages):
            if s in done:
                chips.append(f'<li class="done">{CHECK}{labels[i]}</li>')
            elif state in ("running", "failed") and labels[i] == cur:
                chips.append(f'<li class="active"><span class="ice-dot"></span>{labels[i]}</li>')
            else:
                chips.append(f'<li><span class="ice-hollow"></span>{labels[i]}</li>')
        err = f'<div class="ice-err">✖ {html.escape(j["error"])}</div>' if state == "failed" and j.get("error") else ""
        badge = {"running": "Running", "done": "Done", "failed": "Failed"}.get(state, "Queued")
        cards.append(
            f'<div class="ice-job"><div class="top"><div style="min-width:0"><div class="title">{html.escape(j["job"])}</div>'
            f'<div class="meta">{html.escape(meta)}</div></div><span class="ice-badge {state}">{badge}</span></div>'
            f'<div class="ice-bar"><div class="{"live" if state == "running" else ""}" style="width:{pct}%"></div></div>'
            f'<ul class="ice-chips">{"".join(chips)}</ul>{err}</div>')
    return '<div class="ice-queue">' + "".join(cards) + "</div>"
