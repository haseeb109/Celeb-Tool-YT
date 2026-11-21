"""Timestamped transcript parsing + exact quote lookup.

Supported formats (auto-detected, mix bhi chal jata hai):
  [00:02:14] text      (00:02:14) text      02:14 text      2:14 - text
  timestamp akeli line par, text agli line(s) par (YouTube "Show transcript" copy)
  SRT / VTT  (00:00:12,000 --> 00:00:15,500)
"""
import re
from dataclasses import dataclass, asdict

TS = r"(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?"
LEAD = re.compile(rf"^\s*[\[(]?\s*({TS})\s*[\])]?\s*[-–:|]?\s*(.*)$")
ARROW = re.compile(rf"^\s*({TS})\s*-->\s*({TS})")


def to_sec(ts):
    ts = ts.replace(",", ".")
    parts = [float(p) for p in ts.split(":")]
    s = 0.0
    for p in parts:
        s = s * 60 + p
    return s


def fmt(sec):
    sec = max(0, sec)
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:d}:{s:02d}"


@dataclass
class Line:
    id: str
    start: float
    end: float
    text: str


class Transcript:
    def __init__(self, src_no, raw):
        self.src = src_no
        self.lines = self._parse(raw)
        if len(self.lines) < 5:
            raise ValueError(f"Transcript {src_no}: timestamps parse nahi huay (sirf {len(self.lines)} lines mili)")
        self.by_id = {l.id: l for l in self.lines}

    def _parse(self, raw):
        items = []  # (start, end|None, text)
        cur = None
        for line in raw.splitlines():
            s = line.strip()
            if not s or s.upper() == "WEBVTT" or s.isdigit():
                continue
            m = ARROW.match(s)
            if m:
                cur = [to_sec(m.group(1)), to_sec(m.group(2)), ""]
                items.append(cur)
                continue
            m = LEAD.match(s)
            if m:
                cur = [to_sec(m.group(1)), None, m.group(2).strip()]
                items.append(cur)
                continue
            if cur is not None:
                cur[2] = (cur[2] + " " + s).strip()
        items = [i for i in items if i[2]]
        items.sort(key=lambda x: x[0])
        out = []
        for n, (st, en, tx) in enumerate(items):
            nxt = items[n + 1][0] if n + 1 < len(items) else st + 5
            out.append(Line(f"L{n + 1}", st, en if en else max(nxt, st + 1), tx))
        return out

    def for_prompt(self):
        return "\n".join(f"[{l.id} | {fmt(l.start)}] {l.text}" for l in self.lines)

    def span(self, rng):
        """'L12-L14' or 'L12' -> (start, end, text, [ids])"""
        rng = rng.replace(" ", "").upper()
        a, _, b = rng.partition("-")
        b = b or a
        ia, ib = int(a.lstrip("L")), int(b.lstrip("L"))
        if ia > ib:
            ia, ib = ib, ia
        ids = [f"L{i}" for i in range(ia, ib + 1)]
        missing = [i for i in ids if i not in self.by_id]
        if missing:
            raise KeyError(f"T{self.src}: lines {missing} exist nahi karti")
        ls = [self.by_id[i] for i in ids]
        return ls[0].start, ls[-1].end, " ".join(l.text for l in ls), ids

    def to_dict(self):
        return [asdict(l) for l in self.lines]
