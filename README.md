# lyricmv

**Song + a few images → a lyric music video.** Lyrics are aligned to the vocals with Whisper, every
image gets a slow Ken Burns move, scenes change exactly when a new section starts, and the subtitles
are burned in — all in a single FFmpeg pass. Runs on macOS, Windows, Linux and Docker.

[繁體中文說明](README.zh-TW.md)

```
song.wav ─────────────────────────────────────────────┐
vocals.wav ──► Whisper ──► align to lyrics.txt ──► subtitles (ASS + SRT)
images / clips ──────────────────────────────────────►├──► FFmpeg, one pass ──► song.mp4
scenes.json (which image starts at which section) ────┘     Ken Burns · cross-fades · film grain · subtitles · fades
```

- **Accurate lyric timing**: Whisper's text is only used as a clock. Your original lyrics are matched
  character by character against it, so mishearings, Simplified/Traditional Chinese mix-ups and
  hallucinated credits never reach the screen. Lines Whisper missed are estimated and flagged for you.
- **Scene changes on the music**: tag your lyrics with `[Verse]`, `[Chorus]`, `[Bridge]`… and choose an
  image per section. Each transition starts one second before the section's first word.
- **Images or video clips**: a scene can also be a few seconds of motion from an AI video model (e.g.
  [WanGP](https://github.com/deepbeepmeep/Wan2GP) image-to-video). lyricmv loops it to fill the section
  and still takes care of the timing, transitions, grain and subtitles.
- **Smooth camera**: sub-pixel `perspective` sampling instead of `zoompan`, which rounds to whole pixels
  and visibly jitters on slow zooms.
- **Fast**: each image is decoded once; hardware H.264 (VideoToolbox, NVENC, Quick Sync, AMF) is used
  when it works, libx264 otherwise. A 3½-minute song with 7 scenes renders in about 75 seconds
  on an M2 Max.
- **Ready for YouTube**: 1080p30, BT.709 colour tags, plus an SRT you can upload as closed captions.
- Bundled open-licence CJK fonts (LXGW WenKai TC, Noto Sans TC).

It is tuned for Chinese lyrics (character-level matching). Other languages can be set with `--language`
but are less tested.

## Install

You need **Python 3.10+** and **FFmpeg with libass** (for burning subtitles).

| OS | FFmpeg |
|---|---|
| macOS | `brew install ffmpeg-full` (Homebrew's plain `ffmpeg` has no libass; lyricmv finds `ffmpeg-full` automatically) |
| Windows | `winget install Gyan.FFmpeg` or `choco install ffmpeg-full` |
| Ubuntu / Debian | `sudo apt install ffmpeg` |

Then install lyricmv (with [pipx](https://pipx.pypa.io/) it gets its own environment):

```bash
pipx install git+https://github.com/softwarejob/lyricmv
# Apple Silicon: add the much faster MLX Whisper backend
pipx install "lyricmv[mlx] @ git+https://github.com/softwarejob/lyricmv"
```

Check everything:

```bash
lyricmv doctor
lyricmv demo        # renders lyricmv-demo.mp4, a 12-second sample (no Whisper needed)
```

Using a specific FFmpeg? Set `LYRICMV_FFMPEG=/path/to/ffmpeg`.

## Make a video

You need:

1. **The song** (`song.wav`, mp3, flac…)
2. **A vocals-only stem** (`vocals.wav`) — strongly recommended. Suno can export stems; for other songs
   use a separator such as [Demucs](https://github.com/facebookresearch/demucs) or UVR. Without it
   lyricmv aligns against the full mix, which is less accurate.
3. **lyrics.txt** with section tags (see below)
4. **One image** (or video clip), or several plus a **scenes.json**

```bash
# one image for the whole song
lyricmv make --audio song.wav --vocals vocals.wav --lyrics lyrics.txt --image cover.png

# a different image per section
lyricmv make --audio song.wav --vocals vocals.wav --lyrics lyrics.txt --scenes scenes.json
```

The video is written to `song.mp4`; the transcript, aligned lines and subtitles go to
`lyricmv-work/song/`. The first run downloads the Whisper model (about 1.6 GB). Transcribing a
3½-minute song takes about 15 seconds with MLX on Apple Silicon and about 3 minutes on a CPU.

lyricmv prints every line with its timing and match rate. Lines marked `<- check` were mostly
estimated; watch those parts of the video. If something is off, edit `lines.json` and re-run the
`subs` and `render` steps below — the transcript is cached, so nothing is transcribed again.

### lyrics.txt

```
[Verse 1: soft piano only]
窗外的雨 下了一整夜
桌上的燈 還亮著

[Chorus: drums enter]
慢慢來 沒關係
天總會亮的

[Verse 2]
...

[Chorus]
慢慢來 沒關係
```

- Every lyric line belongs to the `[Section]` above it; anything after `:` in a tag is ignored, so the
  same file can carry Suno-style performance notes.
- A section used once keeps its name (`Verse 2`); repeated ones are numbered: `Chorus#1`, `Chorus#2`.
- A space inside a Chinese line is a phrase break; it is shown as a full-width space.

### scenes.json

```json
{
  "scenes": [
    {"from": "start",    "image": "verse.png"},
    {"from": "Chorus#1", "image": "chorus.png"},
    {"from": "Verse 2",  "image": "verse.png"},
    {"from": "Chorus#2", "image": "chorus.png"}
  ]
}
```

The first scene must be `"start"`. Image paths are relative to the JSON file (or `--images-dir`); a
name without an extension matches `name.png`, `name.jpg`… Any aspect ratio works — images are scaled
to fill 16:9 and centre-cropped. For crisp results use at least 2208×1242 (1920×1080 plus room for
the zoom). [`examples/song`](examples/song) has a sample lyrics.txt and scenes.json (bring your own song
and images).

#### Video clips

A scene can also be a video clip (`.mp4`, `.mov`, `.webm`, `.mkv`), such as a 5–10 second shot that an AI
video model animated from one of your images ([WanGP](https://github.com/deepbeepmeep/Wan2GP) with Wan 2.2
image-to-video, for example). Use it like an image:

```json
{"from": "Chorus#1", "image": "chorus.mp4"}
```

- The clip starts with its section and cross-fades like an image, with the same grain and subtitles on top.
- A clip shorter than its scene loops; a longer one is cut. Clips whose last frame is close to their first
  loop most smoothly.
- Clips are not zoomed (they already move), and their own sound is ignored.
- Any size, aspect ratio and frame rate: clips are scaled to fill 1920×1080 and converted to 30 fps. A
  16 fps clip has to repeat frames and looks a little steppy, so interpolate it to 30 fps first if your
  tool can.
- `--image clip.mp4` puts one clip under the whole song.
- If `chorus.png` and `chorus.mp4` are both there, write the extension: a bare `chorus` is ambiguous.

### Step by step

`make` runs three commands you can also run on their own:

```bash
lyricmv align  --vocals vocals.wav --lyrics lyrics.txt --out work/      # → whisper.json, lines.json
lyricmv subs   --lines work/lines.json                                  # → lyrics.ass, lyrics.srt
lyricmv render --audio song.wav --scenes scenes.json --lines work/lines.json --subs work/lyrics.ass
```

### Useful options

| Option | Default | |
|---|---|---|
| `--zoom` | 1.15 | Ken Burns zoom per image scene; 1.0 = still. Odd scenes push in, even scenes pull out; clips are not zoomed |
| `--transition` | fade | any [xfade](https://ffmpeg.org/ffmpeg-filters.html#xfade) transition: `dissolve`, `smoothleft`, `circleopen`… |
| `--transition-duration` | 1 | seconds |
| `--grain` | 6 | film grain, 0–30 (0 = off) |
| `--fade-in` / `--fade-out` | 1.5 / 2 | seconds, picture and sound |
| `--font`, `--size`, `--margin` | LXGW WenKai TC Medium, 72, 80 | subtitle style; `"Noto Sans TC Medium"` is also bundled |
| `--encoder` | auto | `libx264`, `h264_videotoolbox`, `h264_nvenc`, `h264_qsv`, `h264_amf` |
| `--bitrate` / `--crf` | 12M / 18 | bitrate for hardware encoders (and the cap for libx264); quality for libx264 |
| `--language` | zh | Whisper language, or `auto` |
| `--backend` / `--model` | auto | `mlx` (Apple Silicon) or `faster` (faster-whisper, everywhere) |
| `--force` | | overwrite an existing video (otherwise lyricmv refuses) |

Run `lyricmv <command> --help` for everything.

## Docker

```bash
docker build -t lyricmv https://github.com/softwarejob/lyricmv.git
docker run --rm -v "$PWD:/work" -v lyricmv-models:/models lyricmv \
  make --audio song.wav --vocals vocals.wav --lyrics lyrics.txt --image cover.png
```

The image uses CPU encoding (libx264) and CPU Whisper. The `lyricmv-models` volume keeps the Whisper
model between runs. On Linux add `--user "$(id -u):$(id -g)"` so the video isn't owned by root.

## How it works

- **Alignment**: both texts are normalised (Simplified Chinese, letters and digits only) and matched
  with `difflib`. Matched characters take Whisper's timing; same-length mismatches inside a line are
  treated as homophones and borrow it; leading/trailing gaps are estimated at 0.35 s per character;
  lines with no match share the gap between their neighbours. The first line is anchored to where the
  vocal stem actually gets loud. Whisper runs with `condition_on_previous_text=False` so repeated
  choruses don't trap it in a loop.
- **Subtitles** appear 0.25 s before each line, stay 0.5 s after it, fade 0.3 s, and close gaps under
  0.6 s so they don't flicker.
- **Picture**: each image is scaled once to a working size that leaves room for the zoom
  (2208×1242 at 1.15×), looped, moved with `perspective` (cubic, evaluated per frame), scaled to
  1920×1080 and joined with `xfade`. Grain is added after that, on the final pixels (so it doesn't
  grow with the zoom or double up in cross-fades), luma only. Subtitles and fades come last.
  A video clip is read with `-stream_loop -1`, converted to a constant 30 fps, trimmed to its scene's
  frame count and scaled to fill 1920×1080, so it joins the cross-fades like an image.
- **Colour**: RGB → YUV uses BT.709 and the frames are tagged BT.709, so colours match on YouTube.
  Clips are converted from their own colour tags (untagged clips are read as BT.601, FFmpeg's default).

## Development

```bash
git clone https://github.com/softwarejob/lyricmv && cd lyricmv
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[test]"
pytest
```

## License

lyricmv is MIT licensed. The bundled fonts are under the SIL Open Font License 1.1
([LXGW WenKai TC](https://github.com/lxgw/LxgwWenkaiTC), [Noto Sans TC](https://github.com/notofonts/noto-cjk));
see `src/lyricmv/fonts/licenses/`. lyricmv calls FFmpeg but does not include it; the Docker image installs
Debian's FFmpeg package. Whisper models are downloaded from Hugging Face under their own licences (MIT).

Make sure you have the rights to the music, images and clips you publish.
