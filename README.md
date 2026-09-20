# ytEdit

Qt/PySide6 desktop frontend for yt-dlp + FFmpeg.

## Arch Linux

Install system dependencies:

```bash
sudo pacman -S ffmpeg mpv python
```

Create the environment:

```bash
python -m venv .venv
source .venv/bin/activate.fish
pip install -r requirements.txt
python main.py
```

## Features

- yt-dlp URL analysis and downloads
- quality/format selection
- audio-only downloads
- download queue
- integrated MPV player when `mpv` is available
- precise In/Out selection
- fast cut (`-c copy`) and precise re-encode
- extract audio
- replace audio
- crop/scale/rotate
- volume/fade filters
- concatenate media files
- subtitle download/burning
- FFmpeg command preview
- persistent settings

FFmpeg and ffprobe must be available in `PATH`.
