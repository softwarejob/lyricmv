FROM python:3.12-slim

# Debian's FFmpeg includes libass (subtitles), libx264 and every filter lyricmv uses
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/lyricmv
COPY pyproject.toml README.md README.zh-TW.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

# Whisper models are downloaded on first use; mount a volume at /models to keep them between runs
ENV HF_HOME=/models
WORKDIR /work
ENTRYPOINT ["lyricmv"]
CMD ["--help"]
