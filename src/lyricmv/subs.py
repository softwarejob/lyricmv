"""Aligned lines → ASS (burned into the video) and SRT (for YouTube closed captions)."""
from __future__ import annotations

import re
from pathlib import Path

FONTS_DIR = Path(__file__).resolve().parent / "fonts"
# libass matches the legacy family name including the weight
DEFAULT_FONT = "LXGW WenKai TC Medium"
BUNDLED_FONTS = {
    "LXGW WenKai TC Medium": "LXGWWenKaiTC-Medium.ttf",
    "Noto Sans TC Medium": "NotoSansTC-Medium.otf",
}

# Show each line a little before it is sung, so the fade-in finishes as the voice starts
LEAD = 0.25
# Keep it on screen for a moment after it is sung
HOLD = 0.5
MIN_DURATION = 1.2
# Join lines separated by less than this, so subtitles don't flicker off and on
MERGE_GAP = 0.6
FADE_MS = 300

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Lyric,{font},{size},&H00EAF4FA,&H000000FF,&H00101010,&H96000000,0,0,0,0,100,100,3,0,1,3,2,2,120,120,{margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def display_times(lines):
    """Sung start/end → on-screen start/end."""
    starts = [max(x["start"] - LEAD, 0.0) for x in lines]
    out = []
    for i, x in enumerate(lines):
        end = x["end"] + HOLD
        if i + 1 < len(lines):
            nxt = starts[i + 1]
            end = nxt if nxt - end < MERGE_GAP else min(end, nxt)
        out.append((starts[i], max(end, starts[i] + MIN_DURATION)))
    # stretching to the minimum duration must not overlap the next line
    return [(s, min(e, out[i + 1][0]) if i + 1 < len(out) else e) for i, (s, e) in enumerate(out)]


# CJK punctuation, kana, ideographs, Hangul and full-width forms (～，！)
CJK = "　-ヿ㐀-䶿一-鿿가-힯豈-﫿＀-￯"
_CJK_GAP = re.compile(f"(?<=[{CJK}]) (?=[{CJK}])")


def lyric_text(text):
    # a space between two CJK characters is a phrase break: an ideographic space looks better on screen;
    # spaces between Latin words stay as they are
    return _CJK_GAP.sub("　", " ".join(text.split()))


def ass_time(t):
    cs = round(t * 100)
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def srt_time(t):
    ms = round(t * 1000)
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def build(lines, font=DEFAULT_FONT, size=72, margin=80):
    """Return (ass_text, srt_text)."""
    ass = [ASS_HEADER.format(font=font, size=size, margin=margin)]
    srt = []
    for n, (x, (s, e)) in enumerate(zip(lines, display_times(lines)), 1):
        text = lyric_text(x["text"])
        # braces and backslashes are ASS override syntax; swap them for full-width look-alikes
        safe = text.replace("\\", "＼").replace("{", "｛").replace("}", "｝")
        ass.append(f"Dialogue: 0,{ass_time(s)},{ass_time(e)},Lyric,,0,0,0,,"
                   f"{{\\fad({FADE_MS},{FADE_MS})\\blur1}}{safe}\n")
        srt.append(f"{n}\n{srt_time(s)} --> {srt_time(e)}\n{text}\n")
    return "".join(ass), "\n".join(srt)
