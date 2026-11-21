"""Titles, description, tags, chapters, thumbnail text + .docx export."""
from .transcript import fmt

PACK_TASK = """Create YouTube packaging for this dark investigative celebrity documentary. Same accuracy rule as the script: rumors stay framed as rumors/allegations, no claims that are not in the script.

Return JSON:
{{"titles": ["10 titles, max 70 chars, curiosity-driven, no ALL CAPS sentences, no false claims"],
  "description": "250–400 words, first 2 lines are the hook, then a short summary, then a line noting that claims discussed include allegations and rumors that are unverified",
  "tags": ["15–25 tags"],
  "thumbnail_texts": ["3 options, 2–4 words each"]}}

SCRIPT
{script}
"""


def make_packaging(llm, script_md):
    return llm.json("writer", "You write YouTube packaging for a documentary channel.",
                    PACK_TASK.format(script=script_md.split("# CLIP LOG")[0][:30000]), temperature=0.9)


def chapters(section_starts):
    out = []
    for i, (title, t) in enumerate(section_starts):
        out.append(f"{fmt(0 if i == 0 else t)} {title}")
    return "\n".join(out)


def to_docx(md_text, out_path):
    from docx import Document
    from docx.shared import Pt
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name, st.font.size = "Calibri", Pt(11)
    in_table = None
    for line in md_text.splitlines():
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):
                continue
            if in_table is None:
                in_table = doc.add_table(rows=0, cols=len(cells))
                in_table.style = "Table Grid"
            row = in_table.add_row().cells
            for i, c in enumerate(cells[:len(row)]):
                row[i].text = c.replace("**", "")
            continue
        in_table = None
        if line.startswith("# "):
            doc.add_heading(line[2:], 0 if "CLIP LOG" not in line else 1)
        elif line.startswith("## "):
            doc.add_heading(line[3:], 1)
        elif line.startswith("### "):
            doc.add_heading(line[4:], 2)
        elif line.startswith(">"):
            p = doc.add_paragraph(style="Intense Quote")
            _bold_runs(p, line.lstrip("> ").rstrip())
        elif line.strip() == "---":
            doc.add_page_break()
        elif line.strip():
            _bold_runs(doc.add_paragraph(), line)
    doc.save(out_path)


def _bold_runs(p, text):
    parts = text.split("**")
    for i, part in enumerate(parts):
        r = p.add_run(part.replace("*", ""))
        r.bold = i % 2 == 1
