"""Clean Light theme (Vercel/Notion style) for the Gradio GUI + dark mode. Pure CSS + tiny JS toggle."""
import html
import json

FONTS = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;700&family=JetBrains+Mono:wght@400;500&display=swap"

CSS = """
@import url('""" + FONTS + """');

/* ---------- tokens: Clean Light (default) ---------- */
:root, .gradio-container {
  --ice-bg: #F7F8FA; --ice-text: #0F172A; --ice-sub: #5B6475;
  --ice-acc: #2563EB; --ice-acc2: #60A5FA; --ice-onacc: #FFFFFF;
  --ice-panel: #FFFFFF; --ice-line: #E6E8EC; --ice-hover: #F1F3F6; --ice-track: #EEF0F3;
  --ice-shadow: 0 1px 2px rgba(15,23,42,0.05), 0 4px 16px rgba(15,23,42,0.05);
}
.dark, .dark .gradio-container {
  --ice-bg: #0B0D12; --ice-text: #E8ECF3; --ice-sub: #9AA3B2;
  --ice-acc: #3B82F6; --ice-acc2: #93C5FD; --ice-onacc: #FFFFFF;
  --ice-panel: #12151C; --ice-line: #232833; --ice-hover: #181C25; --ice-track: #1B1F29;
  --ice-shadow: 0 1px 2px rgba(0,0,0,0.4), 0 4px 16px rgba(0,0,0,0.25);
}

/* map onto Gradio's own variables so every component follows */
.gradio-container, .dark .gradio-container {
  --body-background-fill: var(--ice-bg); --background-fill-primary: var(--ice-panel); --background-fill-secondary: var(--ice-hover);
  --block-background-fill: var(--ice-panel); --block-border-color: var(--ice-line); --block-radius: 12px; --block-border-width: 1px;
  --block-label-background-fill: transparent; --block-title-text-color: var(--ice-sub); --block-label-text-color: var(--ice-sub);
  --body-text-color: var(--ice-text); --body-text-color-subdued: var(--ice-sub);
  --border-color-primary: var(--ice-line); --border-color-accent: var(--ice-acc);
  --input-background-fill: var(--ice-hover); --input-border-color: var(--ice-line); --input-radius: 8px;
  --input-background-fill-focus: var(--ice-panel); --input-border-color-focus: var(--ice-acc);
  --input-shadow-focus: 0 0 0 3px color-mix(in srgb, var(--ice-acc) 18%, transparent);
  --button-primary-background-fill: var(--ice-acc); --button-primary-background-fill-hover: var(--ice-acc);
  --button-primary-text-color: var(--ice-onacc); --button-primary-border-color: var(--ice-acc);
  --button-secondary-background-fill: var(--ice-panel); --button-secondary-background-fill-hover: var(--ice-hover);
  --button-secondary-text-color: var(--ice-text); --button-secondary-border-color: var(--ice-line);
  --button-large-radius: 10px; --button-small-radius: 8px; --button-medium-radius: 10px;
  --color-accent: var(--ice-acc); --color-accent-soft: color-mix(in srgb, var(--ice-acc) 12%, transparent);
  --table-even-background-fill: transparent; --table-odd-background-fill: var(--ice-hover);
  --code-background-fill: var(--ice-hover);
  --font: 'Inter', system-ui, sans-serif; --font-mono: 'JetBrains Mono', ui-monospace, monospace;
}

/* ---------- page ---------- */
body, gradio-app { background: var(--ice-bg) !important; color: var(--ice-text); transition: background .3s ease, color .3s ease; }
.gradio-container { max-width: 1200px !important; margin: 0 auto !important; font-family: var(--font) !important; }

/* ---------- panels ---------- */
.block { box-shadow: var(--ice-shadow) !important; border: 1px solid var(--ice-line) !important; border-radius: 12px !important;
         animation: iceRise .35s ease both; transition: border-color .2s ease, background .3s ease; }
.form > .block, .block .block { box-shadow: none !important; animation: none; }
.form { border-radius: 12px !important; }
@keyframes iceRise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
h1, h2, h3 { font-family: 'Inter', var(--font) !important; font-weight: 600 !important; letter-spacing: -0.015em; color: var(--ice-text) !important; }
input, textarea, select { transition: border-color .15s ease, box-shadow .15s ease !important; }

/* ---------- tabs: segmented control ---------- */
.tab-wrapper, .tab-nav, div[role="tablist"] {
  background: var(--ice-track) !important; border: 1px solid var(--ice-line) !important; border-radius: 10px !important;
  padding: 4px !important; gap: 2px; box-shadow: none; }
button[role="tab"] { border: none !important; border-radius: 8px !important; padding: 8px 14px !important; color: var(--ice-sub) !important;
  font-weight: 500 !important; background: transparent !important; transition: color .15s ease, background .2s ease, box-shadow .2s ease !important; }
button[role="tab"]:hover { color: var(--ice-text) !important; }
button[role="tab"][aria-selected="true"], button[role="tab"].selected {
  color: var(--ice-text) !important; background: var(--ice-panel) !important;
  box-shadow: 0 1px 2px rgba(15,23,42,0.08), 0 0 0 1px var(--ice-line) !important; }
button[role="tab"][aria-selected="true"]::after, button[role="tab"].selected::after { display: none !important; }

/* ---------- buttons: lift, press ---------- */
button.lg, button.md, button.sm, .gr-button, button.primary, button.secondary {
  transition: transform .15s ease, box-shadow .2s ease, background .2s ease, border-color .2s ease !important; font-weight: 600 !important; }
button.primary:hover { transform: translateY(-1px); box-shadow: 0 6px 18px color-mix(in srgb, var(--ice-acc) 30%, transparent); }
button.secondary:hover { transform: translateY(-1px); border-color: color-mix(in srgb, var(--ice-acc) 50%, var(--ice-line)) !important; }
button.primary:active, button.secondary:active { transform: scale(.98); }

/* markdown headings/notes: plain text, no panel */
.block:has(.prose):not(:has(input, textarea, select, button, table, audio, video)) {
  background: transparent !important; border: none !important; box-shadow: none !important; animation: none !important;
  overflow: visible !important; padding-left: 2px !important; }

/* ---------- header ---------- */
.ice-plain, .ice-plain > .block, #ice-actions, #ice-actions .block, #ice-head, #ice-head > .block {
  background: transparent !important; border: none !important; box-shadow: none !important; padding: 0 !important; animation: none !important; }
#ice-head { align-items: center !important; flex-wrap: wrap !important; gap: 12px !important;
  border-bottom: 1px solid var(--ice-line) !important; padding-bottom: 14px !important; margin-bottom: 4px; }
#ice-actions { flex-wrap: nowrap !important; gap: 8px !important; align-items: center !important; justify-content: flex-end; }
#ice-actions > * { flex: 0 0 auto !important; min-width: 0 !important; }
.ice-plain .prose:empty, .ice-plain:has(.prose:empty) { display: none; }
#ice-header { display: flex; align-items: center; gap: 12px; }
#ice-header .brand { display: flex; align-items: center; gap: 12px; }
#ice-header .logo { width: 36px; height: 36px; border-radius: 10px; display: flex; align-items: center; justify-content: center;
  background: var(--ice-acc); color: var(--ice-onacc); box-shadow: 0 4px 12px color-mix(in srgb, var(--ice-acc) 30%, transparent); }
#ice-header .name { font-weight: 700; font-size: 18px; letter-spacing: -0.02em; color: var(--ice-text); line-height: 1.15; }
#ice-header .tag { font-size: 12px; color: var(--ice-sub); }
.ice-chip { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--ice-sub); background: var(--ice-panel);
  border: 1px solid var(--ice-line); border-radius: 8px; padding: 6px 10px; white-space: nowrap; }

/* update button: pulse + sheen + spinning feel */
#ice-update { position: relative; overflow: hidden; border-radius: 10px !important; padding: 0 16px !important; min-height: 38px;
  background: var(--ice-acc) !important; color: var(--ice-onacc) !important; border: 1px solid var(--ice-acc) !important;
  animation: icePulse 2.4s infinite; }
#ice-update::before { content: ""; position: absolute; top: 0; bottom: 0; width: 40%; left: -60%;
  background: linear-gradient(100deg, transparent, rgba(255,255,255,.5), transparent); animation: iceSheen 2.8s ease-in-out infinite; }
#ice-update:hover { transform: translateY(-1px); filter: brightness(1.06); }
#ice-update:active { transform: scale(.98); }
#ice-update.latest { animation: none; background: var(--ice-panel) !important; color: var(--ice-text) !important; border-color: var(--ice-line) !important; }
#ice-update.latest::before { display: none; }
@keyframes icePulse { 0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--ice-acc) 45%, transparent); }
  70% { box-shadow: 0 0 0 10px transparent; } 100% { box-shadow: 0 0 0 0 transparent; } }
@keyframes iceSheen { 0% { left: -60%; } 60%, 100% { left: 130%; } }
#ice-theme { border-radius: 10px !important; min-width: 38px !important; min-height: 38px; padding: 0 12px !important; }

/* ---------- toast ---------- */
.ice-toast { animation: iceRise .4s ease both; background: var(--ice-panel); border: 1px solid var(--ice-line); border-left: 3px solid var(--ice-acc);
  border-radius: 10px; padding: 12px 16px; box-shadow: var(--ice-shadow); }
.ice-toast b { color: var(--ice-text); font-weight: 600; }
.ice-toast ul { margin: 8px 0 0; padding-left: 18px; color: var(--ice-sub); font-size: 13px; line-height: 1.6; }

/* ---------- queue cards ---------- */
.ice-queue { display: flex; flex-direction: column; gap: 10px; }
.ice-job { background: var(--ice-panel); border: 1px solid var(--ice-line); border-radius: 12px; padding: 16px 18px;
  box-shadow: var(--ice-shadow); animation: iceRise .35s ease both; transition: transform .2s ease, border-color .2s ease, box-shadow .2s ease; }
.ice-job:hover { transform: translateY(-1px); border-color: color-mix(in srgb, var(--ice-acc) 35%, var(--ice-line));
  box-shadow: 0 2px 4px rgba(15,23,42,0.05), 0 10px 24px rgba(15,23,42,0.07); }
.ice-job .top { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.ice-job .title { font-weight: 600; font-size: 14px; color: var(--ice-text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ice-job .meta { font-size: 12px; color: var(--ice-sub); margin-top: 2px; }
.ice-badge { font-size: 12px; font-weight: 600; padding: 3px 9px; border-radius: 6px; border: 1px solid var(--ice-line); color: var(--ice-sub); white-space: nowrap; }
.ice-badge.running { background: color-mix(in srgb, var(--ice-acc) 12%, transparent); color: var(--ice-acc); border-color: color-mix(in srgb, var(--ice-acc) 35%, transparent); }
.ice-badge.done { color: #15803D; border-color: #15803D40; background: #15803D12; }
.dark .ice-badge.done { color: #4ADE80; border-color: #4ADE8040; background: #4ADE8012; }
.ice-badge.failed { color: #DC2626; border-color: #DC262640; background: #DC262610; }
.ice-bar { margin-top: 12px; height: 6px; border-radius: 999px; background: var(--ice-track); overflow: hidden; }
.ice-bar > div { height: 100%; border-radius: 999px; background: var(--ice-acc); transition: width .6s ease; }
.ice-bar > div.live { background-image: linear-gradient(90deg, var(--ice-acc) 0, var(--ice-acc2) 50%, var(--ice-acc) 100%);
  background-size: 220px 100%; animation: iceShimmer 1.4s linear infinite; }
@keyframes iceShimmer { 0% { background-position: -220px 0; } 100% { background-position: 220px 0; } }
.ice-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; padding: 0; }
.ice-chips li { list-style: none; display: flex; align-items: center; gap: 6px; padding: 4px 9px; border-radius: 6px; font-size: 12px;
  border: 1px solid var(--ice-line); background: var(--ice-hover); color: var(--ice-sub); }
.ice-chips li.done { color: var(--ice-text); } .ice-chips li.done svg { color: var(--ice-acc); }
.ice-chips li.active { color: var(--ice-acc); border-color: color-mix(in srgb, var(--ice-acc) 40%, transparent); background: color-mix(in srgb, var(--ice-acc) 10%, transparent); }
.ice-dot { width: 7px; height: 7px; border-radius: 99px; background: var(--ice-acc); animation: iceBlink 1s infinite; }
.ice-hollow { width: 7px; height: 7px; border-radius: 99px; border: 1.5px solid var(--ice-sub); box-sizing: border-box; }
@keyframes iceBlink { 50% { opacity: .3; } }
.ice-err { margin-top: 10px; font-size: 12px; color: #DC2626; font-family: 'JetBrains Mono', monospace; }
.ice-empty { text-align: center; color: var(--ice-sub); padding: 28px; border: 1px dashed var(--ice-line); border-radius: 12px; background: var(--ice-panel); }

@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; transition: none !important; } }
"""

# theme: default light, remembered per browser
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
    return (f'<div id="ice-header"><div class="brand"><span class="logo">{LOGO}</span><div><div class="name">Celeb Studio</div>'
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
