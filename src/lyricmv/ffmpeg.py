"""Find a usable FFmpeg, check its filters and pick an H.264 encoder that actually works here."""
from __future__ import annotations

import functools
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Filters the renderer always needs
REQUIRED_FILTERS = ("perspective", "xfade", "noise", "scale", "crop", "loop", "fade", "setparams")
# Burning subtitles needs libass, which some builds leave out (e.g. Homebrew's plain `ffmpeg` formula)
SUBTITLE_FILTER = "subtitles"
# Homebrew's ffmpeg-full has libass but is keg-only, so it is not on PATH
MAC_EXTRA = ["/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg", "/usr/local/opt/ffmpeg-full/bin/ffmpeg"]

# Hardware encoders to try before falling back to libx264, in order of preference
HW_ENCODERS = {
    "darwin": ["h264_videotoolbox"],
    "default": ["h264_nvenc", "h264_qsv", "h264_amf"],
}

# RGB → YUV is always BT.709 (HD); these tags tell players and YouTube the same thing
COLOR_ARGS = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]

INSTALL_HINT = """\
Install an FFmpeg build that includes libass:
  macOS:   brew install ffmpeg-full
  Ubuntu:  sudo apt install ffmpeg
  Windows: winget install Gyan.FFmpeg   (or choco install ffmpeg-full)
Or point LYRICMV_FFMPEG at the ffmpeg executable you want to use."""


class FFmpegError(RuntimeError):
    pass


@dataclass(frozen=True)
class FFmpeg:
    ffmpeg: str
    ffprobe: str
    version: str
    filters: frozenset
    encoders: frozenset

    @property
    def has_subtitles(self):
        return SUBTITLE_FILTER in self.filters

    @property
    def missing_filters(self):
        return [f for f in REQUIRED_FILTERS if f not in self.filters]


def _exe(name):
    return name + (".exe" if os.name == "nt" else "")


def _output(cmd):
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode:
        raise FFmpegError(f"{cmd[0]} failed: {res.stderr.strip()[-500:]}")
    return res.stdout


def _table(text, name_col):
    """Names from `ffmpeg -filters` / `-encoders` output (legend rows like `T.. = Timeline` are skipped)."""
    names = set()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) > name_col and parts[name_col] != "=":
            names.add(parts[name_col])
    return names


def inspect(path):
    path = str(path)
    probe = Path(path).with_name(_exe("ffprobe"))
    ffprobe = str(probe) if probe.is_file() else shutil.which("ffprobe")
    if not ffprobe:
        raise FFmpegError(f"found {path} but no ffprobe next to it or on PATH")
    version = _output([path, "-hide_banner", "-version"]).splitlines()[0]
    filters = _table(_output([path, "-hide_banner", "-filters"]), 1)
    encoders = _table(_output([path, "-hide_banner", "-encoders"]), 1)
    return FFmpeg(path, ffprobe, version, frozenset(filters), frozenset(encoders))


def _candidates():
    env = os.environ.get("LYRICMV_FFMPEG")
    if env:
        return [env]
    found = [shutil.which("ffmpeg")]
    if sys.platform == "darwin":
        found += MAC_EXTRA
    seen, out = set(), []
    for p in found:
        if p and Path(p).is_file() and os.path.realpath(p) not in seen:
            seen.add(os.path.realpath(p))
            out.append(p)
    return out


@functools.lru_cache(maxsize=1)
def get_ffmpeg():
    """The best FFmpeg on this machine: one with every required filter and libass if possible."""
    found = []
    for path in _candidates():
        try:
            found.append(inspect(path))
        except (OSError, FFmpegError):
            continue
    if not found:
        raise FFmpegError("FFmpeg not found.\n" + INSTALL_HINT)
    complete = [f for f in found if not f.missing_filters]
    for f in complete:
        if f.has_subtitles:
            return f
    return (complete or found)[0]


@dataclass(frozen=True)
class VideoEncoder:
    name: str
    args: tuple

    @property
    def hardware(self):
        return self.name != "libx264"


def _double(bitrate):
    num = bitrate.rstrip("kKmM")
    return f"{float(num) * 2:g}{bitrate[len(num):]}"


def _encoder_args(name, bitrate, crf):
    if name == "libx264":
        # constant quality, but capped: film grain would otherwise push CRF 18 past 40 Mbps
        return ("-preset", "medium", "-crf", str(crf), "-maxrate", bitrate, "-bufsize", _double(bitrate),
                "-profile:v", "high")
    if name == "h264_nvenc":
        return ("-preset", "p5", "-b:v", bitrate, "-profile:v", "high")
    if name == "h264_amf":
        return ("-quality", "quality", "-b:v", bitrate, "-profile:v", "high")
    # videotoolbox and qsv: a target bitrate is the most reliable knob
    return ("-b:v", bitrate, "-profile:v", "high")


@functools.lru_cache(maxsize=None)
def encoder_works(ffmpeg, name):
    """Listing an encoder doesn't mean the hardware is there, so encode a few tiny frames to be sure."""
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=320x240:r=30:d=0.2",
           "-vf", "format=yuv420p", "-c:v", name, "-frames:v", "5", "-f", "null", "-"]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def pick_video_encoder(ff, preference="auto", bitrate="12M", crf=18):
    if preference != "auto":
        if preference not in ff.encoders:
            raise FFmpegError(f"this FFmpeg has no {preference} encoder")
        if not encoder_works(ff.ffmpeg, preference):
            raise FFmpegError(f"{preference} is listed but failed a test encode (no hardware or driver?)")
        return VideoEncoder(preference, _encoder_args(preference, bitrate, crf))
    order = HW_ENCODERS.get(sys.platform, HW_ENCODERS["default"]) + ["libx264"]
    for name in order:
        if name in ff.encoders and encoder_works(ff.ffmpeg, name):
            return VideoEncoder(name, _encoder_args(name, bitrate, crf))
    raise FFmpegError("no working H.264 encoder (libx264 or hardware) in this FFmpeg build")


def audio_encoder(ff):
    # macOS AudioToolbox AAC is several times faster than FFmpeg's native encoder at 320k
    return "aac_at" if "aac_at" in ff.encoders else "aac"


def filter_path(path):
    """A file path as a filter option value, escaped for both filtergraph levels.

    Works with Windows drive letters (C:), spaces, quotes, commas and brackets.
    """
    s = Path(path).resolve().as_posix()
    # level 1: inside a filter's key=value list
    s = s.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
    # level 2: inside the filtergraph
    for ch in "\\'[],;":
        s = s.replace(ch, "\\" + ch)
    return s


def probe_duration(ff, path):
    out = _output([ff.ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)])
    return float(out.split()[0])


def probe_video(ff, path):
    """(codec, width, height) of the first video stream."""
    out = _output([ff.ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                   "stream=codec_name,width,height", "-of", "default=nw=1:nk=1", str(path)])
    codec, width, height = out.split()[:3]
    return codec, int(width), int(height)


def count_frames(ff, path):
    out = _output([ff.ffprobe, "-v", "error", "-count_packets", "-select_streams", "v:0",
                   "-show_entries", "stream=nb_read_packets", "-of", "default=nw=1:nk=1", str(path)])
    return int(out.split()[0])
