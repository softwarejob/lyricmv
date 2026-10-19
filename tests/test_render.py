import json
import os
import subprocess

import pytest

from lyricmv import cli
from lyricmv import ffmpeg as fx
from lyricmv import render as rd


def ffmpeg_or_skip(need_subtitles=True):
    try:
        ff = fx.get_ffmpeg()
    except fx.FFmpegError:
        pytest.skip("FFmpeg not installed")
    if ff.missing_filters or (need_subtitles and not ff.has_subtitles):
        pytest.skip("FFmpeg lacks required filters / libass")
    return ff


def test_timeline_adds_up_to_the_song():
    scenes = [rd.Scene(None, 0.0), rd.Scene(None, 30.0), rd.Scene(None, 61.5)]
    offsets, lengths = rd.timeline(scenes, 200.0, 1.0)
    assert offsets == [0.0, 29.0, 60.5]
    # cross-faded total = sum of clips - overlaps = song length
    assert sum(lengths) - 1.0 * (len(scenes) - 1) == pytest.approx(200.0)


def test_timeline_rejects_scenes_too_close():
    with pytest.raises(ValueError):
        rd.timeline([rd.Scene(rd.Path("a.png"), 0.0), rd.Scene(rd.Path("b.png"), 1.5)], 100.0, 1.0)


def test_load_scenes(tmp_path):
    (tmp_path / "verse.png").write_bytes(b"")
    (tmp_path / "chorus.jpg").write_bytes(b"")
    plan = {"scenes": [{"from": "start", "image": "verse.png"}, {"from": "Chorus#1", "image": "chorus"}]}
    (tmp_path / "scenes.json").write_text(json.dumps(plan))
    lines = [{"section": "Verse", "start": 5.0}, {"section": "Chorus#1", "start": 40.0},
             {"section": "Chorus#1", "start": 44.0}]
    scenes = rd.load_scenes(tmp_path / "scenes.json", lines)
    assert [(s.image.name, s.start) for s in scenes] == [("verse.png", 0.0), ("chorus.jpg", 40.0)]

    (tmp_path / "bad.json").write_text(json.dumps([{"from": "Bridge", "image": "verse.png"}]))
    with pytest.raises(ValueError, match="Bridge"):
        rd.load_scenes(tmp_path / "bad.json", lines)


def test_work_size_covers_full_zoom():
    w, h = rd.work_size(1.15)
    assert (w, h) == (2208, 1242)
    assert w / 1.15 >= rd.W and h / 1.15 >= rd.H


def test_filter_path_escaping():
    s = fx.filter_path("/tmp/a b/it's,[x];y:z.ass")
    assert "\\\\\\'" in s and "\\," in s and "\\[" in s and "\\;" in s and "\\\\:" in s


@pytest.mark.skipif(os.name == "nt", reason="':' and quotes are not allowed in Windows file names")
def test_subtitles_in_a_hostile_path(tmp_path):
    ff = ffmpeg_or_skip()
    folder = tmp_path / "a b, it's [x]; y:z"
    folder.mkdir()
    ass = folder / "lyrics.ass"
    ass.write_text("[Script Info]\nScriptType: v4.00+\nPlayResX: 320\nPlayResY: 240\n\n[Events]\n"
                   "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                   "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,hi\n", encoding="utf-8")
    cmd = [ff.ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.5",
           "-vf", f"subtitles=filename={fx.filter_path(ass)}:fontsdir={fx.filter_path(folder)}",
           "-f", "null", "-"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


def test_demo_renders(tmp_path):
    ff = ffmpeg_or_skip()
    out = tmp_path / "demo.mp4"
    with pytest.raises(SystemExit) as done:
        cli.main(["demo", "--out", str(out), "--encoder", "libx264"])
    assert done.value.code == 0
    assert fx.probe_video(ff, out) == ("h264", 1920, 1080)
    assert fx.probe_duration(ff, out) == pytest.approx(12.0, abs=0.1)
    assert fx.count_frames(ff, out) == 12 * rd.FPS


def test_refuses_to_overwrite(tmp_path):
    ffmpeg_or_skip()
    out = tmp_path / "demo.mp4"
    out.write_bytes(b"keep me")
    with pytest.raises(SystemExit) as done:
        cli.main(["demo", "--out", str(out)])
    assert done.value.code == 1
    assert out.read_bytes() == b"keep me"
