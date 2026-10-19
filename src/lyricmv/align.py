"""Align the original lyrics to the vocal track.

Whisper's text is only used as a timing reference — it mishears homophones, mixes Simplified and
Traditional Chinese and hallucinates credits in instrumental breaks. Its characters are matched
against the real lyrics one by one, and the matched timings are carried back to each lyric line.
"""
from __future__ import annotations

import difflib
import re

import numpy as np
from opencc import OpenCC

# About how long one sung character lasts; used to place characters Whisper missed
CHAR_SECONDS = 0.35
# Lines matching less than this are flagged for a manual check
LOW_MATCH = 0.5

_t2s = OpenCC("t2s").convert


def norm(text):
    """Comparison form: Simplified Chinese, letters and digits only."""
    return re.sub(r"[^\w]|_", "", _t2s(text)).lower()


def parse_lyrics(text):
    """lyrics.txt → [{"section", "text"}].

    Section tags look like `[Verse 1]` or `[Chorus: drums enter]` (anything after `:` is ignored).
    Sections that appear once keep their name; repeated ones become `Chorus#1`, `Chorus#2`, ...
    """
    lines, counts, section = [], {}, None
    for n, raw in enumerate(text.splitlines(), 1):
        raw = raw.strip()
        if not raw:
            continue
        m = re.match(r"\[([^\]:]+)", raw)
        if m:
            name = m.group(1).strip()
            counts[name] = counts.get(name, 0) + 1
            section = {"name": name, "n": counts[name]}
            continue
        if section is None:
            raise ValueError(f"line {n}: put a [Section] tag (e.g. [Verse 1]) before the first lyric line")
        lines.append({"section": section, "text": raw})
    if not lines:
        raise ValueError("no lyric lines found")
    for ln in lines:
        s = ln["section"]
        ln["section"] = s["name"] if counts[s["name"]] == 1 else f"{s['name']}#{s['n']}"
    return lines


def whisper_chars(result):
    """Split Whisper's words into characters, sharing each word's time evenly: (char, start, end, segment)."""
    chars = []
    for s, seg in enumerate(result["segments"]):
        for w in seg.get("words") or []:
            text = norm(w["word"])
            if not text:
                continue
            step = (w["end"] - w["start"]) / len(text)
            chars += [(c, w["start"] + i * step, w["start"] + (i + 1) * step, s) for i, c in enumerate(text)]
    return chars


def homophone_ok(lyric, wchars, i1, i2, j1, j2):
    """Can a same-length mismatch borrow Whisper's timings character by character?

    Inside one line, yes (a misheard homophone). Across lines, no: if Whisper stretched the last word
    of a line into two characters, the extra one must not be lent to the first word of the next line.
    So when the span touches a line start/end, Whisper's side must sit at a segment start/end too.
    """
    lines = {lyric[k][0] for k in range(i1, i2)}
    if len(lines) != 1:
        return False
    line = lines.pop()
    at_line_start = i1 == 0 or lyric[i1 - 1][0] != line
    at_line_end = i2 == len(lyric) or lyric[i2][0] != line
    at_seg_start = j1 == 0 or wchars[j1 - 1][3] != wchars[j1][3]
    at_seg_end = j2 == len(wchars) or wchars[j2][3] != wchars[j2 - 1][3]
    return (not at_line_start or at_seg_start) and (not at_line_end or at_seg_end)


def vocal_onset(samples, rate=16000, threshold_db=-35.0, window=0.05):
    """First moment the vocal track gets louder than `threshold_db`: the anchor for the first line."""
    n = int(rate * window)
    if len(samples) < n:
        return 0.0
    mono = np.asarray(samples, dtype=np.float64)
    rms = np.sqrt(np.mean(mono[: len(mono) // n * n].reshape(-1, n) ** 2, axis=1))
    loud = np.nonzero(20 * np.log10(rms + 1e-12) > threshold_db)[0]
    return float(loud[0] * window) if len(loud) else 0.0


def align(lines, wchars, onset):
    """Give every lyric line a start and end time. Returns [{"section", "text", "start", "end", "match"}]."""
    lyric = [(i, c) for i, ln in enumerate(lines) for c in norm(ln["text"])]
    sm = difflib.SequenceMatcher(None, [c for _, c in lyric], [w[0] for w in wchars], autojunk=False)
    times = [None] * len(lyric)
    exact = [False] * len(lyric)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        # same-length replacements are almost always misheard homophones: borrow the timings
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1
                              and homophone_ok(lyric, wchars, i1, i2, j1, j2)):
            for k in range(i2 - i1):
                times[i1 + k] = wchars[j1 + k][1:3]
                exact[i1 + k] = tag == "equal"

    out, prev_end = [], onset
    for i, ln in enumerate(lines):
        idx = [k for k, (li, _) in enumerate(lyric) if li == i]
        hit = [k for k in idx if times[k]]
        # the match ratio only counts real matches, not borrowed homophone timings
        ratio = sum(exact[k] for k in idx) / len(idx) if idx else 0.0
        if hit:
            lead = hit[0] - idx[0]  # unmatched characters at the start of the line
            start = max(times[hit[0]][0] - lead * CHAR_SECONDS, prev_end)
            tail = idx[-1] - hit[-1]
            end = times[hit[-1]][1] + tail * CHAR_SECONDS
        else:
            start, end = None, None  # nothing matched: interpolate from the neighbours below
        if i == 0 and (not hit or hit[0] != idx[0]):
            start = onset  # the first line starts when the voice actually starts
        out.append({"section": ln["section"], "text": ln["text"], "start": start, "end": end,
                    "match": round(ratio, 2)})
        if end is not None:
            prev_end = end

    # unmatched lines: share the gap between the previous end and the next start by character count
    i = 0
    while i < len(out):
        if out[i]["end"] is not None:
            i += 1
            continue
        j = i
        while j < len(out) and out[j]["end"] is None:
            j += 1
        left = out[i - 1]["end"] if i > 0 else onset
        if out[i]["start"] is not None:
            left = out[i]["start"]
        sizes = [max(len(norm(x["text"])), 1) for x in out[i:j]]
        right = out[j]["start"] if j < len(out) else left + CHAR_SECONDS * sum(sizes)
        t = left
        for x, n in zip(out[i:j], sizes):
            x["start"] = round(t, 2)
            t += (right - left) * n / sum(sizes)
            x["end"] = round(t, 2)
        i = j

    for x in out:
        x["start"], x["end"] = round(x["start"], 2), round(x["end"], 2)
    for a, b in zip(out, out[1:]):  # a line must not run into the next one
        a["end"] = min(a["end"], b["start"])
    return out
