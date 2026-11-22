"""'purple_box' frame for original voice clips (Style 1 / cloutville template).

Measured from 3 reference videos (NexLev watch):
  - animated deep-purple smoky background + vignette + light grain
  - clip centered, ~66% of frame, rounded corners (~18px), white border (~4px), soft drop shadow
  - progress bar directly under the clip, same width, ~5px, white fill on dim track,
    fills left→right from the clip's first frame to its last (every clip, no minimum length)
  - hard cut in/out, clip itself static
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

DEFAULT = {
    "bg_colors": ["0x3b0066", "0x7a12c9", "0x9c1de6", "0x5a0aa0"],
    "box_scale": 0.66, "radius": 18, "border_px": 4, "border_color": [255, 255, 255],
    "bar_px": 5, "bar_gap": 14, "bar_fill": "white", "bar_track": "0x5a4a6e",
    "shadow": True, "grain": 6,
}


def _assets(work: Path, bw, bh, s, spec):
    """Pillow-rendered static layers (cached by size): alpha mask, border ring, shadow."""
    work.mkdir(parents=True, exist_ok=True)
    r = max(2, int(spec["radius"] * s))
    tag = f"{bw}x{bh}_{r}"
    mask, border, shadow = work / f"mask_{tag}.png", work / f"border_{tag}.png", work / f"shadow_{tag}.png"
    if not mask.exists():
        m = Image.new("L", (bw, bh), 0)
        ImageDraw.Draw(m).rounded_rectangle([0, 0, bw - 1, bh - 1], radius=r, fill=255)
        m.save(mask)
    if not border.exists():
        bp = max(1, int(spec["border_px"] * s))
        b = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        ImageDraw.Draw(b).rounded_rectangle([0, 0, bw - 1, bh - 1], radius=r,
                                            outline=tuple(spec["border_color"]) + (255,), width=bp)
        b.save(border)
    if not shadow.exists():
        pad = int(40 * s)
        sh = Image.new("RGBA", (bw + 2 * pad, bh + 2 * pad), (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle([pad, pad + int(10 * s), pad + bw, pad + bh + int(10 * s)], radius=r, fill=(0, 0, 0, 150))
        sh.filter(ImageFilter.GaussianBlur(int(18 * s))).save(shadow)
    return mask, border, shadow, int(40 * s)


def build(src_w, src_h, W, H, dur, fps, work: Path, spec=None):
    """Returns (extra_inputs, filter_complex_video, out_label). Input 0 = the clip."""
    sp = {**DEFAULT, **(spec or {})}
    s = W / 1920
    # box size: fit clip aspect inside box_scale of the frame (leave room for the bar)
    maxw, maxh = int(W * sp["box_scale"]), int(H * sp["box_scale"])
    ar = (src_w / src_h) if src_h else 16 / 9
    bw, bh = (maxw, int(maxw / ar)) if maxw / ar <= maxh else (int(maxh * ar), maxh)
    bw, bh = bw // 2 * 2, bh // 2 * 2
    bar_h, gap = max(2, int(sp["bar_px"] * s)), int(sp["bar_gap"] * s)
    bx = (W - bw) // 2
    by = (H - bh - gap - bar_h) // 2
    bar_y = by + bh + gap
    mask, border, shadow, pad = _assets(work, bw, bh, s, sp)
    c = sp["bg_colors"]
    inputs = [
        "-f", "lavfi", "-t", f"{dur:.3f}", "-i",
        f"gradients=s={W}x{H}:r={fps}:c0={c[0]}:c1={c[1]}:c2={c[2]}:c3={c[3]}:nb_colors=4:type=radial:speed=0.012:seed=7",
        "-loop", "1", "-t", f"{dur:.3f}", "-i", str(shadow),
        "-loop", "1", "-t", f"{dur:.3f}", "-i", str(mask),
        "-loop", "1", "-t", f"{dur:.3f}", "-i", str(border),
        "-f", "lavfi", "-t", f"{dur:.3f}", "-i", f"color=c={sp['bar_track']}:s={bw}x{bar_h}:r={fps}",
        "-f", "lavfi", "-t", f"{dur:.3f}", "-i", f"color=c={sp['bar_fill']}:s={bw}x{bar_h}:r={fps}",
    ]
    grain = f",noise=alls={int(sp['grain'])}:allf=t" if sp.get("grain") else ""
    fc = (
        # background: smoky purple, soft, vignetted
        f"[1:v]boxblur=40:2,vignette=PI/5{grain},format=yuv420p,setsar=1[bg];"
        # clip: fit box, rounded corners via alpha mask
        f"[0:v]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},setsar=1,fps={fps},format=rgba[cl];"
        f"[3:v]format=gray,scale={bw}:{bh}[mk];[cl][mk]alphamerge[clr];"
        # progress bar: fill slides in over the track, clipped to track size → grows left→right over the clip
        f"[6:v]format=rgba[fill];[5:v]format=rgba[trk];"
        f"[trk][fill]overlay=x='-w+w*min(1,t/{max(dur, 0.1):.3f})':y=0:eval=frame:shortest=1[bar];"
        # stack layers
        f"[bg][2:v]overlay={bx - pad}:{by - pad}:shortest=1[l1];"
        f"[l1][clr]overlay={bx}:{by}:shortest=1[l2];"
        f"[l2][4:v]overlay={bx}:{by}:shortest=1[l3];"
        f"[l3][bar]overlay={bx}:{bar_y}:shortest=1,format=yuv420p,setsar=1"
    )
    return inputs, fc


def probe_wh(path):
    import json
    import subprocess
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "json", str(path)], capture_output=True, text=True).stdout
    try:
        st = json.loads(out)["streams"][0]
        return int(st["width"]), int(st["height"])
    except Exception:
        return 1920, 1080
