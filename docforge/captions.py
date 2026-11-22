"""Style-driven burned captions (.ass): ALL CAPS, bold, outline, 1–3 words at a time, one emphasis word highlighted."""
import re


def _ass_t(s):
    h, r = divmod(max(0, s), 3600)
    m, r = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{r:05.2f}"


def _bgr(rgb):
    r, g, b = rgb
    return f"&H00{b:02X}{g:02X}{r:02X}"


STOP = set("the a an and or but of to in on at for is was are were be been it its this that with as by from he she they his her their you i we".split())


def write_ass(words, out, W, H, spec):
    """words: [(word, start, end)] absolute times. spec from style profile 'captions'."""
    n = int(spec.get("words_per_chunk", 2))
    col, hi = _bgr(spec.get("color_rgb", [255, 255, 255])), _bgr(spec.get("highlight_rgb", [255, 214, 0]))
    size = int(H * spec.get("size_ratio", 0.075))
    pos = spec.get("position", "lower")
    align, marginv = (5, 0) if pos == "center" else (2, int(H * 0.16))
    font = spec.get("font", "Impact")
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{size},{col},{col},&H00000000,&H96000000,1,0,0,0,100,100,1,0,1,{max(3, size // 14)},{max(2, size // 22)},{align},60,60,{marginv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for i in range(0, len(words), n):
        grp = words[i:i + n]
        if not grp:
            continue
        toks = [re.sub(r"[^\w'’-]", "", w).upper() for w, _, _ in grp]
        cand = [k for k, t in enumerate(toks) if t.lower() not in STOP and len(t) > 3]
        emph = max(cand, key=lambda k: len(toks[k])) if cand else -1
        txt = " ".join((f"{{\\c{hi}}}{t}{{\\c{col}}}" if k == emph else t) for k, t in enumerate(toks) if t)
        if not txt:
            continue
        pop = "{\\fscx80\\fscy80\\t(0,90,\\fscx100\\fscy100)}" if spec.get("pop", True) else ""
        lines.append(f"Dialogue: 0,{_ass_t(grp[0][1])},{_ass_t(grp[-1][2] + 0.05)},Cap,,0,0,0,,{pop}{txt}")
    out.write_text(head + "\n".join(lines) + "\n")
    return out
