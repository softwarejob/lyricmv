"""Speech-to-text with word timestamps.

Every backend returns the same shape:
  {"backend": ..., "model": ..., "segments": [{"text", "start", "end", "words": [{"word", "start", "end"}]}]}
"""
from __future__ import annotations

import importlib.util
import platform
import subprocess
import sys

import numpy as np

MLX_MODEL = "mlx-community/whisper-large-v3-turbo"
FASTER_MODEL = "large-v3-turbo"


def _has(module):
    return importlib.util.find_spec(module) is not None


def apple_silicon():
    return sys.platform == "darwin" and platform.machine() == "arm64"


def available_backends():
    found = []
    if apple_silicon() and _has("mlx_whisper"):
        found.append("mlx")
    if _has("faster_whisper"):
        found.append("faster")
    return found


def pick_backend(name="auto"):
    found = available_backends()
    if name == "auto":
        if not found:
            raise RuntimeError("no Whisper backend installed: pip install faster-whisper"
                               + ("  (or on Apple Silicon: pip install 'lyricmv[mlx]')" if apple_silicon() else ""))
        return found[0]
    if name not in found:
        hint = "pip install 'lyricmv[mlx]' (Apple Silicon only)" if name == "mlx" else "pip install faster-whisper"
        raise RuntimeError(f"Whisper backend '{name}' is not available here: {hint}")
    return name


def _clean(segments):
    out = []
    for s in segments:
        words = [{"word": w["word"], "start": float(w["start"]), "end": float(w["end"])} for w in s.get("words") or []]
        out.append({"text": s.get("text", ""), "start": float(s["start"]), "end": float(s["end"]), "words": words})
    return out


def load_audio(ffmpeg, path, rate=16000):
    """Decode any audio file to 16 kHz mono float32 with our FFmpeg.

    Both backends accept arrays, so neither depends on PyAV or on an `ffmpeg` being on PATH.
    """
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(path), "-map", "0:a:0",
           "-ac", "1", "-ar", str(rate), "-f", "f32le", "-"]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode:
        raise RuntimeError(f"could not decode {path}: {res.stderr.decode('utf-8', 'replace').strip()[-300:]}")
    return np.frombuffer(res.stdout, dtype="<f4").copy()


def transcribe(samples, language="zh", backend="auto", model=None):
    """Transcribe 16 kHz mono samples (see load_audio) with word timestamps. `language=None` auto-detects."""
    backend = pick_backend(backend)
    if backend == "mlx":
        import mlx_whisper

        model = model or MLX_MODEL
        result = mlx_whisper.transcribe(
            samples, path_or_hf_repo=model, language=language, word_timestamps=True,
            # repeated choruses easily trap Whisper in a loop when it conditions on its own output
            condition_on_previous_text=False, verbose=None,
        )
        segments = result["segments"]
    else:
        import ctranslate2
        from faster_whisper import WhisperModel

        model = model or FASTER_MODEL
        cuda = ctranslate2.get_cuda_device_count() > 0
        whisper = WhisperModel(model, device="cuda" if cuda else "cpu", compute_type="float16" if cuda else "int8")
        parts, _ = whisper.transcribe(samples, language=language, word_timestamps=True,
                                      condition_on_previous_text=False, beam_size=5)
        segments = [{"text": s.text, "start": s.start, "end": s.end,
                     "words": [{"word": w.word, "start": w.start, "end": w.end} for w in s.words or []]}
                    for s in parts]
    return {"backend": backend, "model": model, "segments": _clean(segments)}
