"""Images or video clips + song (+ subtitles) → 1080p music video, in a single FFmpeg encode.

Per scene: fill 16:9 → slow Ken Burns push for images (sub-pixel `perspective`, no jitter), or the clip
itself, looped to the scene's length → cross-fade into the next scene right before its section starts.
Then film grain, burned-in subtitles and fades.
"""
from __future__ import annotations

import json
import math
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import ffmpeg as fx

W, H, FPS = 1920, 1080, 30
# Film grain strength (FFmpeg `noise`, luma only): luma standard deviation ≈ 0.55 × grain
GRAIN = 6
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")
# e.g. a few seconds of motion from an image-to-video model
VIDEO_EXTS = (".mp4", ".mov", ".webm", ".mkv")


def is_video(path):
    return Path(path).suffix.lower() in VIDEO_EXTS


@dataclass(frozen=True)
class Scene:
    image: Path  # a still image or a video clip
    start: float  # when its section's first line is sung (0 for the first scene)

    @property
    def is_video(self):
        return is_video(self.image)


def resolve_image(ref, base):
    """`ref` is a file path (relative to `base`), or a bare name matched against `base/<name>.*`.

    Images and video clips both count, so a bare name that matches more than one file (say `chorus.png`
    and the `chorus.mp4` animated from it) has to be written with its extension.
    """
    path = Path(ref)
    if not path.is_absolute():
        path = Path(base) / path
    if path.is_file():
        return path
    if not path.suffix:
        found = sorted(p for p in path.parent.glob(path.name + ".*")
                       if p.suffix.lower() in IMAGE_EXTS + VIDEO_EXTS)
        if len(found) > 1:
            raise ValueError(f"{ref!r} matches {', '.join(p.name for p in found)}: add the extension of the one "
                             "you want")
        if found:
            return found[0]
    raise FileNotFoundError(f"image or clip not found: {ref} (looked in {base})")


def load_scenes(scenes_file, lines, images_dir=None):
    """Scene plan + aligned lines → [Scene].

    The plan is `{"scenes": [{"from": "start" | "<section>", "image": "<file>"}, ...]}` (or just the list).
    Sections use the names from lines.json: `Verse 2`, or `Chorus#2` for the second chorus.
    """
    data = json.loads(Path(scenes_file).read_text(encoding="utf-8"))
    plan = data.get("scenes") if isinstance(data, dict) else data
    if not plan:
        raise ValueError(f"{scenes_file} has no scenes")
    starts = {}
    for line in lines:
        starts.setdefault(line["section"], line["start"])
    base = images_dir or Path(scenes_file).parent
    scenes = []
    for s in plan:
        if s["from"] == "start":
            t = 0.0
        elif s["from"] in starts:
            t = float(starts[s["from"]])
        else:
            raise ValueError(f"section {s['from']!r} is not in the lyrics (sections: {', '.join(starts)})")
        scenes.append(Scene(resolve_image(s["image"], base), t))
    if scenes[0].start != 0.0:
        raise ValueError('the first scene must be {"from": "start", ...}')
    return scenes


def timeline(scenes, duration, tdur):
    """Cross-fade offsets and clip lengths.

    A transition starts `tdur` seconds before its section's first line and finishes as it is sung.
    Scene k covers [offset_k, offset_{k+1} + tdur], so the cross-faded total is exactly the song length.
    """
    offsets = [0.0] + [s.start - tdur for s in scenes[1:]]
    ends = [o + tdur for o in offsets[1:]] + [duration]
    lengths = [e - o for o, e in zip(offsets, ends)]
    for scene, o, length in zip(scenes, offsets, lengths):
        if length < 2 * tdur:
            raise ValueError(f"scene {scene.image.name} at {o:.1f}s is only {length:.1f}s long: "
                             "sections too close together or out of order")
    return offsets, lengths


def work_size(zoom):
    """Push-in working resolution: at full zoom the sampled area is still a full 1920x1080."""
    return 2 * math.ceil(round(W / 2 * zoom, 6)), 2 * math.ceil(round(H / 2 * zoom, 6))


def build_filtergraph(n, offsets, lengths, duration, zoom=1.15, fade_in=1.5, fade_out=2.0, transition="fade",
                      tdur=1.0, subs=None, fontsdir=None, grain=GRAIN, videos=()):
    """`videos[i]` is true when scene i is a video clip (its input looped with `-stream_loop -1`)."""
    ww, wh = work_size(zoom)
    parts = []
    for i, length in enumerate(lengths):
        frames = round(length * FPS)
        if i < len(videos) and videos[i]:
            parts.append(",".join([
                # V = the real picture, not cover art
                f"[{i}:V:0]setpts=PTS-STARTPTS",
                # constant 30 fps, after setpts so the link keeps a known 30/1 rate: the same frame rate and
                # time base (1/30) as the image scenes, as xfade requires
                f"fps={FPS}",
                # cut the endlessly looped clip to the scene's length; the clip moves on its own, so no Ken Burns
                f"trim=end_frame={frames}",
                # YUV → YUV: swscale reads the clip's colour tags (untagged = BT.601, FFmpeg's own default
                # when it encodes RGB frames) and converts to BT.709, like the images
                f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos"
                ":out_color_matrix=bt709:out_range=tv",
                f"crop={W}:{H}",
                "setsar=1",
                f"format=yuv420p[s{i}]",
            ]))
            continue
        span = f"{zoom - 1:.6f}*in/{max(frames - 1, 1)}"
        # odd scenes pull out, even scenes push in, so the camera changes direction at each cut
        z = f"({zoom:.6f}-{span})" if i % 2 else f"(1+{span})"
        hw, hh = f"W/2/{z}", f"H/2/{z}"
        parts.append(",".join([
            # any aspect ratio: fill 16:9, crop the rest; RGB → YUV as BT.709 so colours survive YouTube
            f"[{i}:v]scale={ww}:{wh}:force_original_aspect_ratio=increase:flags=lanczos"
            ":out_color_matrix=bt709:out_range=tv",
            f"crop={ww}:{wh}",
            "format=yuv420p",
            # decode and scale the image once, then repeat it (instead of re-decoding a 4K PNG every frame)
            f"loop=loop={frames - 1}:size=1:start=0",
            "setpts=N",
            # FFmpeg 7.x marks the rate unknown after setpts, and xfade needs a constant frame rate;
            # the timestamps are already one per frame, so this neither drops nor duplicates frames
            f"fps={FPS}",
            # perspective samples at sub-pixel positions; zoompan rounds to whole pixels and jitters
            "perspective=interpolation=cubic:eval=frame:"
            f"x0='W/2-{hw}':y0='H/2-{hh}':x1='W/2+{hw}':y1='H/2-{hh}':"
            f"x2='W/2-{hw}':y2='H/2+{hh}':x3='W/2+{hw}':y3='H/2+{hh}'",
            f"scale={W}:{H}:flags=lanczos",
            f"format=yuv420p[s{i}]",
        ]))
    last = "s0"
    for k in range(1, n):
        parts.append(f"[{last}][s{k}]xfade=transition={transition}:duration={tdur}:offset={offsets[k]:.3f}[x{k}]")
        last = f"x{k}"
    fade_out_start = max(duration - fade_out, 0)
    post = []
    if grain:
        # grain on the final 1080p pixels: it doesn't grow with the zoom and doesn't double up in
        # cross-fades; luma only, because chroma noise looks like a cheap camera
        post.append(f"noise=c0s={grain}:c0f=t")
    if subs:
        post.append(f"subtitles=filename={fx.filter_path(subs)}"
                    + (f":fontsdir={fx.filter_path(fontsdir)}" if fontsdir else ""))
    post += [
        # fades come last so subtitles fade out with the picture
        f"fade=t=in:st=0:d={fade_in}",
        f"fade=t=out:st={fade_out_start:.3f}:d={fade_out}",
        # otherwise libx264 negotiates 4:4:4, which most players (and the high profile) don't support
        "format=yuv420p",
        # hardware encoders ignore -colorspace etc.; tag the frames themselves
        "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv[v]",
    ]
    parts.append(f"[{last}]" + ",".join(post))
    parts.append(f"[{n}:a:0]afade=t=in:st=0:d={fade_in},afade=t=out:st={fade_out_start:.3f}:d={fade_out}[a]")
    return ";".join(parts)


def render(audio, scenes, out, subs=None, fontsdir=None, zoom=1.15, transition="fade", tdur=1.0,
           fade_in=1.5, fade_out=2.0, grain=GRAIN, encoder="auto", bitrate="12M", crf=18, force=False, log=print):
    ff = fx.get_ffmpeg()
    if ff.missing_filters:
        raise fx.FFmpegError(f"{ff.ffmpeg} lacks filters: {', '.join(ff.missing_filters)}\n{fx.INSTALL_HINT}")
    if subs and not ff.has_subtitles:
        raise fx.FFmpegError(f"{ff.ffmpeg} was built without libass, so it can't burn subtitles.\n{fx.INSTALL_HINT}")
    if not 1.0 <= zoom <= 1.5:
        raise ValueError("zoom must be between 1.0 and 1.5")
    if not 0 <= grain <= 30:
        raise ValueError("grain must be between 0 and 30 (0 = off)")
    out = Path(out)
    if out.exists() and not force:
        raise FileExistsError(f"{out} already exists; use --force to overwrite it")
    out.parent.mkdir(parents=True, exist_ok=True)
    # write to a temporary name first, so an interrupted render never leaves a half-finished video
    tmp = out.with_name(out.stem + ".part.mp4")

    duration = fx.probe_duration(ff, audio)
    offsets, lengths = timeline(scenes, duration, tdur)
    clips = {s.image: fx.probe_clip(ff, s.image) for s in scenes if s.is_video}
    venc = fx.pick_video_encoder(ff, encoder, bitrate, crf)
    aenc = fx.audio_encoder(ff)

    inputs = []
    for scene in scenes:
        if scene.is_video:
            # loop a clip that is shorter than its scene; its own sound is never used
            inputs += ["-an", "-stream_loop", "-1", "-i", str(scene.image)]
        else:
            # -framerate makes the image's time base 1/30, so setpts=N is exactly one frame per tick
            inputs += ["-framerate", str(FPS), "-i", str(scene.image)]
    graph = build_filtergraph(len(scenes), offsets, lengths, duration, zoom, fade_in, fade_out, transition, tdur,
                              subs, fontsdir, grain, [s.is_video for s in scenes])
    cmd = [ff.ffmpeg, "-hide_banner", "-loglevel", "error", "-stats", "-y", *inputs, "-i", str(audio),
           "-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-t", f"{duration:.3f}",
           "-c:v", venc.name, *venc.args, *fx.COLOR_ARGS, "-c:a", aenc, "-b:a", "320k",
           "-movflags", "+faststart", str(tmp)]

    log(f"Rendering {Path(audio).name} ({duration:.1f}s), {len(scenes)} scene(s), "
        f"encoder {venc.name}{' (hardware)' if venc.hardware else ''}"
        + (", subtitles" if subs else "") + (f", grain {grain}" if grain else ""))
    for i, (scene, o, length) in enumerate(zip(scenes, offsets, lengths)):
        when = "start" if i == 0 else f"{int(scene.start // 60)}:{scene.start % 60:05.2f} (transition at {o:.2f}s)"
        if scene.is_video:
            clip_len, clip_fps = clips[scene.image]
            how = "clip" + (f" {clip_len:.1f}s" if clip_len else "") + (f" {clip_fps:g} fps" if clip_fps else "")
            if clip_len and clip_len < length - 0.05:
                how += f", looped to {length:.1f}s"
        else:
            how = "pull out" if i % 2 else "push in"
        log(f"  {when:<34} {scene.image.name} ({how})")
    t0 = time.monotonic()
    try:
        res = subprocess.run(cmd)
        if res.returncode:
            raise fx.FFmpegError("FFmpeg failed; no output was written")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    elapsed = time.monotonic() - t0

    out_duration = fx.probe_duration(ff, tmp)
    codec, width, height = fx.probe_video(ff, tmp)
    if abs(out_duration - duration) > 0.1 or (codec, width, height) != ("h264", W, H):
        raise fx.FFmpegError(f"output check failed: {codec} {width}x{height}, {out_duration:.2f}s "
                             f"(song is {duration:.2f}s); the temporary file is kept at {tmp}")
    tmp.replace(out)
    log(f"Done: {out}  ({width}x{height} {codec}, {out_duration:.2f}s, {out.stat().st_size / 1e6:.1f} MB, "
        f"{elapsed:.1f}s = {duration / elapsed:.1f}x realtime)")
    return out
