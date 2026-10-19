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


def test_resolve_image_finds_clips(tmp_path):
    (tmp_path / "rain.mp4").write_bytes(b"")
    assert rd.resolve_image("rain", tmp_path).name == "rain.mp4"
    assert rd.Scene(tmp_path / "rain.MOV", 0.0).is_video and not rd.Scene(tmp_path / "rain.png", 0.0).is_video
    # an image and the clip animated from it: the bare name is ambiguous
    (tmp_path / "rain.png").write_bytes(b"")
    with pytest.raises(ValueError, match="rain.mp4, rain.png"):
        rd.resolve_image("rain", tmp_path)
    assert rd.resolve_image("rain.png", tmp_path).name == "rain.png"


def test_filtergraph_video_scene():
    graph = rd.build_filtergraph(2, [0.0, 2.0], [3.0, 7.0], 9.0, videos=[False, True])
    image, clip = graph.split(";")[:2]
    assert image.startswith("[0:v]") and "perspective=" in image
    # a clip moves on its own: no Ken Burns, just 30 fps cut to the scene's 7 s
    assert clip.startswith("[1:V:0]") and "perspective" not in clip and "loop=" not in clip
    assert "fps=30" in clip and "trim=end_frame=210" in clip and clip.endswith("[s1]")
    assert clip.index("setpts") < clip.index("fps=") < clip.index("trim=")


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


def _gray_frames(ff, path, frames, size=(192, 108)):
    """Selected frames as small grayscale images (bytes)."""
    pick = "+".join(f"eq(n\\,{n})" for n in frames)
    res = subprocess.run([ff.ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(path), "-vf",
                          f"select='{pick}',scale={size[0]}:{size[1]},format=gray", "-fps_mode", "passthrough",
                          "-f", "rawvideo", "-"], capture_output=True, check=True)
    n = size[0] * size[1]
    assert len(res.stdout) == n * len(frames)
    return [res.stdout[k * n:(k + 1) * n] for k in range(len(frames))]


def _diff(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def test_image_and_looped_clip(tmp_path):
    ff = ffmpeg_or_skip(need_subtitles=False)
    run = ["-hide_banner", "-loglevel", "error", "-y"]
    # a 3 s, 24 fps clip with its own sound (which must be ignored), a still image and a 9 s song
    subprocess.run([ff.ffmpeg, *run, "-f", "lavfi", "-i", "testsrc=s=640x360:r=24:d=3", "-f", "lavfi",
                    "-i", "sine=f=880:d=3", "-pix_fmt", "yuv420p", "-shortest", str(tmp_path / "clip.mp4")],
                   check=True)
    subprocess.run([ff.ffmpeg, *run, "-f", "lavfi", "-i", "color=c=0x0b2e33:s=1920x1080:d=1", "-frames:v", "1",
                    str(tmp_path / "still.png")], check=True)
    subprocess.run([ff.ffmpeg, *run, "-f", "lavfi", "-i", "sine=f=220:d=9", str(tmp_path / "song.wav")], check=True)
    plan = {"scenes": [{"from": "start", "image": "still"}, {"from": "Chorus", "image": "clip"}]}
    (tmp_path / "scenes.json").write_text(json.dumps(plan))
    lines = [{"section": "Verse", "start": 0.5}, {"section": "Chorus", "start": 3.0}]
    scenes = rd.load_scenes(tmp_path / "scenes.json", lines)
    assert [s.is_video for s in scenes] == [False, True]

    out = tmp_path / "mv.mp4"
    # the clip's scene runs 2.0 → 9.0 s, more than twice the clip, so it has to loop
    rd.render(tmp_path / "song.wav", scenes, out, encoder="libx264", grain=0, log=lambda *a: None)
    assert fx.probe_video(ff, out) == ("h264", 1920, 1080)
    assert fx.probe_duration(ff, out) == pytest.approx(9.0, abs=0.1)
    assert fx.count_frames(ff, out) == 9 * rd.FPS
    # the clip's scene starts at frame 60; 90 frames (one 3 s loop) later the same clip frame is back,
    # while 6 frames later the picture has moved: it loops seamlessly and doesn't freeze
    first, moved, looped = _gray_frames(ff, out, [105, 111, 195])
    assert _diff(first, looped) < 0.2 * _diff(first, moved)
