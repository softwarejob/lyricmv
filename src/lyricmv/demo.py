"""Synthetic assets for `lyricmv demo`: a short tone, two gradient images and pre-aligned lyrics."""
from __future__ import annotations

import json
import subprocess

from . import ffmpeg as fx

DURATION = 12
LINES = [
    {"section": "Verse", "text": "這是 lyricmv 的示範", "start": 1.5, "end": 3.8},
    {"section": "Verse", "text": "歌詞會自動對上歌聲", "start": 4.0, "end": 6.2},
    {"section": "Chorus", "text": "Every line on time", "start": 7.0, "end": 9.0},
    {"section": "Chorus", "text": "換一張圖 換一種光", "start": 9.2, "end": 10.8},
]
SCENES = {"scenes": [{"from": "start", "image": "verse.png"}, {"from": "Chorus", "image": "chorus.png"}]}
# teal shadows, warm amber highlights
GRADIENTS = {"verse.png": ("0x0b2e33", "0xc98b4a"), "chorus.png": ("0x1d1035", "0xe8a95c")}


def _run(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode:
        raise fx.FFmpegError(res.stderr.strip()[-500:])


def make_demo_assets(folder):
    ff = fx.get_ffmpeg()
    base = [ff.ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for name, (c0, c1) in GRADIENTS.items():
        if "gradients" in ff.filters:
            src = f"gradients=s=1920x1080:c0={c0}:c1={c1}:x0=0:y0=1080:x1=1920:y1=0:nb_colors=2:d=1"
        else:
            src = f"color=c={c0}:s=1920x1080:d=1"
        _run(base + ["-f", "lavfi", "-i", src, "-frames:v", "1", str(folder / name)])
    # a soft A-minor chord with a slow swell
    tone = "+".join(f"0.06*sin(2*PI*{f}*t)" for f in (220.0, 261.63, 329.63)) + ")*(0.7+0.3*sin(2*PI*0.25*t))"
    _run(base + ["-f", "lavfi", "-i", f"aevalsrc='({tone}|({tone}':s=48000:d={DURATION}",
                 "-c:a", "pcm_s16le", str(folder / "song.wav")])
    (folder / "lines.json").write_text(json.dumps(LINES, ensure_ascii=False, indent=1), encoding="utf-8")
    (folder / "scenes.json").write_text(json.dumps(SCENES, indent=1), encoding="utf-8")
    return {"audio": folder / "song.wav", "lines": folder / "lines.json", "scenes": folder / "scenes.json"}
