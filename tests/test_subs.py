import pytest

from lyricmv import subs as sb


def test_display_times_lead_hold_and_merge():
    lines = [{"start": 10.0, "end": 12.0}, {"start": 12.8, "end": 14.0}, {"start": 20.0, "end": 20.3}]
    times = sb.display_times(lines)
    # appears 0.25 s early
    assert times[0][0] == 10.0 - sb.LEAD
    # gap to the next line (12.55 - 12.5) is under MERGE_GAP, so the first line runs up to it
    assert times[0][1] == times[1][0] == 12.8 - sb.LEAD
    # a short last line is held for at least MIN_DURATION
    assert times[2][1] - times[2][0] == pytest.approx(sb.MIN_DURATION)


def test_display_times_never_overlap():
    lines = [{"start": 1.0, "end": 1.1}, {"start": 1.5, "end": 3.0}]
    (s1, e1), (s2, e2) = sb.display_times(lines)
    assert e1 <= s2


def test_lyric_text_spaces():
    assert sb.lyric_text("我還在 線上") == "我還在　線上"
    assert sb.lyric_text("喔～ 機房會關燈") == "喔～　機房會關燈"
    assert sb.lyric_text("Every  line on time") == "Every line on time"
    assert sb.lyric_text("這是 lyricmv 的示範") == "這是 lyricmv 的示範"


def test_time_formats():
    assert sb.ass_time(3725.456) == "1:02:05.46"
    assert sb.srt_time(3725.456) == "01:02:05,456"


def test_build_escapes_override_braces():
    ass, srt = sb.build([{"text": "a{b}c\\d", "start": 1.0, "end": 2.0}])
    dialogue = ass.splitlines()[-1]
    assert dialogue.endswith("a｛b｝c＼d")
    assert "Style: Lyric,LXGW WenKai TC Medium,72," in ass
    assert srt.startswith("1\n00:00:00,750 --> ")


def test_bundled_fonts_exist():
    for file in sb.BUNDLED_FONTS.values():
        assert (sb.FONTS_DIR / file).is_file()
