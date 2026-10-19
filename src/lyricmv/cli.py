"""Command line: lyricmv doctor | demo | align | subs | render | make."""
from __future__ import annotations

import argparse
import json
import platform
import sys
import tempfile
from pathlib import Path

from . import __version__, align as al, ffmpeg as fx, render as rd, subs as sb, whisper as wh


def _setup_console():
    # Windows pipes default to a legacy code page; lyrics are usually CJK
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (AttributeError, ValueError):
            pass


# ---------------------------------------------------------------- doctor

def cmd_doctor(args):
    print(f"lyricmv {__version__} · Python {platform.python_version()} · {platform.system()} {platform.machine()}")
    ok = True
    try:
        ff = fx.get_ffmpeg()
    except fx.FFmpegError as e:
        print(f"[x] FFmpeg: {e}")
        return 1
    print(f"[ok] FFmpeg: {ff.ffmpeg}\n     {ff.version}")
    if ff.missing_filters:
        ok = False
        print(f"[x] missing filters: {', '.join(ff.missing_filters)}")
    if ff.has_subtitles:
        print("[ok] libass (subtitles filter)")
    else:
        ok = False
        print(f"[x] no libass: subtitles can't be burned in\n{fx.INSTALL_HINT}")
    try:
        venc = fx.pick_video_encoder(ff)
        print(f"[ok] video encoder: {venc.name}" + (" (hardware)" if venc.hardware else " (CPU)"))
    except fx.FFmpegError as e:
        ok = False
        print(f"[x] video encoder: {e}")
    print(f"[ok] audio encoder: {fx.audio_encoder(ff)}")
    backends = wh.available_backends()
    if backends:
        print(f"[ok] Whisper backends: {', '.join(backends)} (auto picks {backends[0]})")
    else:
        ok = False
        print("[x] no Whisper backend: pip install faster-whisper")
    if wh.apple_silicon() and "mlx" not in backends:
        print("     tip: pip install 'lyricmv[mlx]' for much faster transcription on Apple Silicon")
    for name, file in sb.BUNDLED_FONTS.items():
        print(f"[{'ok' if (sb.FONTS_DIR / file).is_file() else 'x'}] font: {name}")
    print("Ready." if ok else "Some checks failed (see [x] above).")
    return 0 if ok else 1


# ---------------------------------------------------------------- steps

def run_align(vocals, lyrics, out_dir, language="zh", backend="auto", model=None, retranscribe=False):
    lines = al.parse_lyrics(Path(lyrics).read_text(encoding="utf-8"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = out_dir / "whisper.json"
    source = {"file": Path(vocals).name, "size": Path(vocals).stat().st_size}
    samples = wh.load_audio(fx.get_ffmpeg().ffmpeg, vocals)
    result = None
    if cache.is_file() and not retranscribe:
        result = json.loads(cache.read_text(encoding="utf-8"))
        if result.get("source", source) != source:
            result = None  # cached transcript belongs to another file
        else:
            print(f"Using cached transcript {cache} (--retranscribe to redo it)")
    if result is None:
        name = wh.pick_backend(backend)
        print(f"Transcribing {Path(vocals).name} with Whisper ({name}); the first run downloads the model…")
        result = wh.transcribe(samples, None if language == "auto" else language, name, model)
        result["source"] = source
        cache.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    onset = al.vocal_onset(samples)
    aligned = al.align(lines, al.whisper_chars(result), onset)
    path = out_dir / "lines.json"
    path.write_text(json.dumps(aligned, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Voice starts at {onset:.2f}s")
    flagged = 0
    for x in aligned:
        flag = "  <- check" if x["match"] < al.LOW_MATCH else ""
        flagged += bool(flag)
        print(f"{x['start']:7.2f}-{x['end']:7.2f}  {x['match']:4.0%}  [{x['section']}] {x['text']}{flag}")
    print(f"Wrote {path}" + (f"; {flagged} line(s) matched poorly and were estimated, check their timing"
                             if flagged else ""))
    return aligned, path


def run_subs(lines_file, out_dir=None, font=sb.DEFAULT_FONT, size=72, margin=80):
    lines = json.loads(Path(lines_file).read_text(encoding="utf-8"))
    out_dir = Path(out_dir or Path(lines_file).parent)
    out_dir.mkdir(parents=True, exist_ok=True)
    ass, srt = sb.build(lines, font, size, margin)
    (out_dir / "lyrics.ass").write_text(ass, encoding="utf-8")
    (out_dir / "lyrics.srt").write_text(srt, encoding="utf-8")
    print(f"{len(lines)} subtitle line(s), font {font}: {out_dir / 'lyrics.ass'}, {out_dir / 'lyrics.srt'}")
    return out_dir / "lyrics.ass"


def scenes_from_args(args, lines):
    if args.image:
        return [rd.Scene(Path(args.image), 0.0)]
    if lines is None:
        raise ValueError("--scenes needs --lines (the output of `lyricmv align`) to know when sections start")
    return rd.load_scenes(args.scenes, lines, args.images_dir)


def render_kwargs(args):
    return dict(zoom=args.zoom, transition=args.transition, tdur=args.transition_duration, fade_in=args.fade_in,
                fade_out=args.fade_out, grain=args.grain, encoder=args.encoder, bitrate=args.bitrate, crf=args.crf,
                force=args.force, fontsdir=args.fonts_dir or sb.FONTS_DIR)


# ---------------------------------------------------------------- commands

def cmd_align(args):
    out = args.out or Path("lyricmv-work") / Path(args.vocals).stem
    run_align(args.vocals, args.lyrics, out, args.language, args.backend, args.model, args.retranscribe)


def cmd_subs(args):
    run_subs(args.lines, args.out, args.font, args.size, args.margin)


def cmd_render(args):
    lines = json.loads(Path(args.lines).read_text(encoding="utf-8")) if args.lines else None
    scenes = scenes_from_args(args, lines)
    out = args.out or Path(args.audio).with_suffix(".mp4").name
    rd.render(args.audio, scenes, out, subs=args.subs, **render_kwargs(args))


def cmd_make(args):
    stem = Path(args.audio).stem
    work = Path(args.workdir or Path("lyricmv-work") / stem)
    out = Path(args.out or f"{stem}.mp4")
    if out.exists() and not args.force:
        raise FileExistsError(f"{out} already exists; use --force to overwrite it")
    vocals = args.vocals
    if not vocals:
        vocals = args.audio
        print("No --vocals given: aligning against the full mix. A vocals-only stem (e.g. from Suno stems or "
              "Demucs) gives much better timing.")
    print("1/3 Aligning lyrics")
    lines, _ = run_align(vocals, args.lyrics, work, args.language, args.backend, args.model, args.retranscribe)
    print("2/3 Building subtitles")
    ass = run_subs(work / "lines.json", work, args.font, args.size, args.margin)
    print("3/3 Rendering video")
    rd.render(args.audio, scenes_from_args(args, lines), out, subs=ass, **render_kwargs(args))


def cmd_demo(args):
    from .demo import make_demo_assets

    out = Path(args.out)
    with tempfile.TemporaryDirectory(prefix="lyricmv-demo-") as tmp:
        assets = make_demo_assets(Path(tmp))
        ass = run_subs(assets["lines"], tmp)
        lines = json.loads(assets["lines"].read_text(encoding="utf-8"))
        scenes = rd.load_scenes(assets["scenes"], lines)
        rd.render(assets["audio"], scenes, out, subs=ass, encoder=args.encoder, force=args.force,
                  fontsdir=sb.FONTS_DIR)
    print(f"Open {out} to see what lyricmv does. Next: lyricmv make --help")


# ---------------------------------------------------------------- parser

def add_align_options(p):
    p.add_argument("--language", default="zh", help="lyrics language for Whisper, or 'auto' (default: zh)")
    p.add_argument("--backend", default="auto", choices=["auto", "mlx", "faster"],
                   help="Whisper backend: mlx (Apple Silicon) or faster-whisper (everywhere); default auto")
    p.add_argument("--model", help=f"Whisper model (default: {wh.MLX_MODEL} for mlx, {wh.FASTER_MODEL} for faster)")
    p.add_argument("--retranscribe", action="store_true", help="ignore the cached whisper.json and transcribe again")


def add_subs_options(p):
    p.add_argument("--font", default=sb.DEFAULT_FONT,
                   help=f"subtitle font: {' or '.join(repr(f) for f in sb.BUNDLED_FONTS)} are bundled; any installed "
                        f"font or one in --fonts-dir also works (default: {sb.DEFAULT_FONT!r})")
    p.add_argument("--size", type=int, default=72, help="font size at 1080p (default: 72)")
    p.add_argument("--margin", type=int, default=80, help="distance from the bottom edge in pixels (default: 80)")


def add_render_options(p):
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--image", type=Path,
                     help="one background image or video clip for the whole song (any aspect ratio; a short clip "
                          "loops)")
    src.add_argument("--scenes", type=Path, help="scene plan JSON: which image or clip starts at which lyric section")
    p.add_argument("--images-dir", type=Path, help="where --scenes images and clips live (default: next to the JSON)")
    p.add_argument("--fonts-dir", type=Path, help="extra font folder for subtitles (default: bundled fonts)")
    p.add_argument("--out", type=Path, help="output .mp4 (default: <song name>.mp4 in the current folder)")
    p.add_argument("--zoom", type=float, default=1.15,
                   help="Ken Burns zoom per image scene, 1.0 = still; clips are not zoomed (default: 1.15)")
    p.add_argument("--transition", default="fade", help="xfade transition: fade, dissolve, smoothleft… (default: fade)")
    p.add_argument("--transition-duration", type=float, default=1.0, help="seconds (default: 1)")
    p.add_argument("--fade-in", type=float, default=1.5, help="seconds (default: 1.5)")
    p.add_argument("--fade-out", type=float, default=2.0, help="seconds (default: 2)")
    p.add_argument("--grain", type=int, default=rd.GRAIN, help=f"film grain 0-30, 0 = off (default: {rd.GRAIN})")
    p.add_argument("--encoder", default="auto",
                   help="H.264 encoder: auto, libx264, h264_videotoolbox, h264_nvenc, h264_qsv, h264_amf "
                        "(default: auto = first hardware encoder that works, else libx264)")
    p.add_argument("--bitrate", default="12M", help="bitrate for hardware encoders (default: 12M)")
    p.add_argument("--crf", type=int, default=18, help="quality for libx264, lower = better (default: 18)")
    p.add_argument("--force", action="store_true", help="overwrite the output if it exists")


def build_parser():
    ap = argparse.ArgumentParser(prog="lyricmv", description="Song + images → lyric music video, rendered by FFmpeg.")
    ap.add_argument("--version", action="version", version=f"lyricmv {__version__}")
    sub = ap.add_subparsers(dest="command", required=True, metavar="command")

    p = sub.add_parser("doctor", help="check FFmpeg, encoders, Whisper and fonts")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("demo", help="render a 12-second sample video (no Whisper needed)")
    p.add_argument("--out", default="lyricmv-demo.mp4")
    p.add_argument("--encoder", default="auto")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("make", help="all steps: align lyrics → subtitles → video")
    p.add_argument("--audio", required=True, type=Path, help="the full song (wav, mp3, flac…)")
    p.add_argument("--vocals", type=Path, help="vocals-only stem for alignment (recommended)")
    p.add_argument("--lyrics", required=True, type=Path, help="lyrics.txt with [Section] tags")
    p.add_argument("--workdir", type=Path, help="where whisper.json, lines.json and subtitles go "
                                                "(default: lyricmv-work/<song name>)")
    add_align_options(p)
    add_subs_options(p)
    add_render_options(p)
    p.set_defaults(func=cmd_make)

    p = sub.add_parser("align", help="align lyrics.txt to the vocals → lines.json")
    p.add_argument("--vocals", required=True, type=Path, help="vocals-only stem (or the full song)")
    p.add_argument("--lyrics", required=True, type=Path, help="lyrics.txt with [Section] tags")
    p.add_argument("--out", type=Path, help="output folder (default: lyricmv-work/<vocals name>)")
    add_align_options(p)
    p.set_defaults(func=cmd_align)

    p = sub.add_parser("subs", help="lines.json → lyrics.ass + lyrics.srt")
    p.add_argument("--lines", required=True, type=Path)
    p.add_argument("--out", type=Path, help="output folder (default: next to lines.json)")
    add_subs_options(p)
    p.set_defaults(func=cmd_subs)

    p = sub.add_parser("render", help="images or clips + song (+ subtitles) → mp4")
    p.add_argument("--audio", required=True, type=Path)
    p.add_argument("--lines", type=Path, help="lines.json from `lyricmv align` (needed with --scenes)")
    p.add_argument("--subs", type=Path, help="ASS subtitles to burn in (from `lyricmv subs`)")
    add_render_options(p)
    p.set_defaults(func=cmd_render)
    return ap


def main(argv=None):
    _setup_console()
    args = build_parser().parse_args(argv)
    for name in ("audio", "vocals", "lyrics", "image", "scenes", "lines", "subs"):
        path = getattr(args, name, None)
        if path and not Path(path).is_file():
            print(f"error: file not found: {path}", file=sys.stderr)
            sys.exit(2)
    try:
        sys.exit(args.func(args) or 0)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(130)
    except (ValueError, RuntimeError, OSError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
