import numpy as np
import pytest

from lyricmv import align as al


def test_parse_lyrics_numbers_repeated_sections():
    text = """
[Verse 1: soft guitar]
第一句
第二句

[Chorus]
副歌一

[Verse 2]
第三句

[Chorus]
副歌二
"""
    lines = al.parse_lyrics(text)
    assert [x["section"] for x in lines] == ["Verse 1", "Verse 1", "Chorus#1", "Verse 2", "Chorus#2"]
    assert [x["text"] for x in lines] == ["第一句", "第二句", "副歌一", "第三句", "副歌二"]


def test_parse_lyrics_needs_a_section_first():
    with pytest.raises(ValueError):
        al.parse_lyrics("沒有標籤的歌詞\n[Verse]\n第一句")
    with pytest.raises(ValueError):
        al.parse_lyrics("[Verse]\n\n")


def test_norm_simplifies_and_strips_punctuation():
    assert al.norm("還在，線上！") == al.norm("还在线上")
    assert al.norm("Hello, World") == "helloworld"


def words(*items):
    """[(text, start, end)] → one Whisper segment."""
    return {"words": [{"word": w, "start": s, "end": e} for w, s, e in items]}


def test_align_exact_match():
    lines = al.parse_lyrics("[Verse]\n你好世界\n再見朋友")
    result = {"segments": [words(("你好", 1.0, 2.0), ("世界", 2.0, 3.0)),
                           words(("再見", 4.0, 5.0), ("朋友", 5.0, 6.0))]}
    out = al.align(lines, al.whisper_chars(result), onset=1.0)
    assert [(x["start"], x["end"], x["match"]) for x in out] == [(1.0, 3.0, 1.0), (4.0, 6.0, 1.0)]


def test_align_borrows_homophone_timing_but_does_not_count_it_as_a_match():
    lines = al.parse_lyrics("[Verse]\n你好世界\n再見朋友")
    # Whisper misheard 好 as 號
    result = {"segments": [words(("你號", 1.0, 2.0), ("世界", 2.0, 3.0)),
                           words(("再見", 4.0, 5.0), ("朋友", 5.0, 6.0))]}
    out = al.align(lines, al.whisper_chars(result), onset=1.0)
    assert (out[0]["start"], out[0]["end"]) == (1.0, 3.0)
    assert out[0]["match"] == 0.75


def test_align_interpolates_a_missing_line():
    lines = al.parse_lyrics("[Verse]\n第一句歌詞\n完全聽不到\n最後一句了")
    result = {"segments": [words(("第一句歌詞", 1.0, 3.0)), words(("最後一句了", 7.0, 9.0))]}
    out = al.align(lines, al.whisper_chars(result), onset=1.0)
    assert out[1]["match"] == 0.0
    assert out[0]["end"] <= out[1]["start"] < out[1]["end"] <= out[2]["start"]
    assert (out[1]["start"], out[1]["end"]) == (3.0, 7.0)


def test_first_line_starts_at_the_voice_when_its_start_is_missed():
    lines = al.parse_lyrics("[Verse]\n作詞作曲你好")
    # Whisper only caught the end of the line
    result = {"segments": [words(("你好", 5.0, 6.0))]}
    out = al.align(lines, al.whisper_chars(result), onset=3.2)
    assert out[0]["start"] == 3.2


def test_vocal_onset():
    rate = 16000
    t = np.arange(rate * 2) / rate
    samples = np.where(t >= 1.0, 0.3 * np.sin(2 * np.pi * 440 * t), 0.0).astype(np.float32)
    assert al.vocal_onset(samples, rate) == pytest.approx(1.0, abs=0.06)
    assert al.vocal_onset(np.zeros(rate, np.float32), rate) == 0.0
