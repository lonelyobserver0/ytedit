# ytEdit

A Qt/PySide6 desktop frontend for yt-dlp + FFmpeg.

## Arch Linux

System dependencies:

```bash
sudo pacman -S ffmpeg mpv python
# mpv also provides libmpv, used by the built-in player
```

Launching (on first run the scripts create the virtual environment and install
the dependencies, then they simply start the application):

```bash
./run.sh          # bash
./run.fish        # fish
```

Options common to both scripts:

| Option | Effect |
|---|---|
| `-x`, `--xcb` | force `QT_QPA_PLATFORM=xcb` (already chosen automatically on Wayland when XWayland is available) |
| `-w`, `--wayland` | stay on native Wayland: the mpv preview opens in a separate window |
| `-u`, `--update` | reinstall/upgrade the Python dependencies |
| `-c`, `--check` | check the environment and dependencies, then exit |
| `-h`, `--help` | show the help |

Unrecognised arguments are passed through to `main.py`. Dependencies are only
reinstalled when `requirements.txt` changes (or with `--update`).

Manual installation, as an alternative:

```bash
python -m venv .venv
source .venv/bin/activate.fish
pip install -r requirements.txt
python main.py
```

`ffmpeg` and `ffprobe` must be in the `PATH`; `mpv` is only needed for the
preview. For an environment diagnosis: `python -m ytedit.doctor`.

## Features

**Download**
- URL analysis with yt-dlp (asynchronous, the interface never freezes)
- quality selection (up to 1080p/720p/480p/360p) and container (MP4/MKV/WEBM)
- audio only: **original** (no re-encoding, the default) or opus, m4a, mp3,
  flac, wav — the source from YouTube is already lossy, so converting
  it to flac adds nothing and recompressing it to mp3 takes something away
- subtitles with language selection (`it,en` or `all`)
- **Whole playlist** option: when off (the default) a URL containing `&list=`
  downloads only the video it points to; when on it downloads the entire
  playlist into a subfolder, numbered in order
- sequential download queue with per-item status
- extra yt-dlp arguments (one per line, e.g. `--cookies-from-browser firefox`)
- progress bar driven by yt-dlp's real percentages

**Suggested workflow**

1. paste the URL and press **Analyze**: the video opens in the editor straight
   away and starts **streaming** through mpv + yt-dlp — nothing is downloaded
2. pick the IN and OUT points while watching the preview
   (`IN = position` / `OUT = position`)
3. decide what you want (video or audio only, quality, container) and press
   **⬇ Download IN–OUT**: yt-dlp downloads *only* that range
   (`--download-sections`), not the whole video
4. the local file replaces the URL in the editor and the FFmpeg tools become
   available for touch-ups

The **IN–OUT selection only** checkbox in the Download tab does the same thing
from the Download button.

**Editor**
- **built-in video player**: libmpv is rendered inside a Qt OpenGL widget, so
  the video stays in the window even on native Wayland (this is not mpv as an
  external process attached with `--wid`, which requires X11)
- playback streamed directly from a URL, with no download up front
- OSC bar controls, pause, stop, ±5 s jumps and exact seeking (not snapped to a
  keyframe)
- **timeline** below the video: a draggable playhead to scrub back and forth,
  IN/OUT handles to delimit the segment, with the selection highlighted and its
  duration shown; kept in sync both ways with the IN and OUT fields
- `IN = position` / `OUT = position` buttons, which read the time from the
  player over IPC
- fast cutting (`-c copy`) or precise cutting (re-encode)
- two opposite actions on the selection: **keep the selection only**, or
  **remove the selection**, which drops the range and stitches the remaining
  parts back together in a single FFmpeg pass (`trim` + `concat`)
- audio extraction, audio track replacement
- scaling, rotation, volume, audio fade in/out

**Tools**
- merging several files, with or without re-encoding
- subtitles: burned into the video (burn-in) or embedded as a track

**Advanced**
- live preview of the yt-dlp and FFmpeg commands that will be run
- interruption of the FFmpeg operation in progress
- persistent settings (destination, quality, format, languages, window geometry)

## Appearance

Three themes, selectable in the **Advanced** tab and applied live, without a
restart:

| Theme | Where it comes from |
|---|---|
| `dark` | the default |
| `light` | for anyone working with light in their face |
| `pywal` | read from `~/.cache/wal/colors.json`, only shown if that file exists |

What changes is the palette, not the meaning of the colours: the accent marks
whatever is selected or active, a second colour appears only on the action that
destroys, and the video frame stays dark in every theme, because an image is
judged against a neutral surround.

For pywal, the accent and the danger colour are picked by saturation and hue
rather than by index: `color1` is not reliably "the red one", it depends on the
image.

Interface in Adwaita Sans, timecodes and commands in JetBrains Mono (tabular
figures). It all lives in `ytedit/theme.py`.

## Notes

- **Video player**: with `python-mpv` installed (it is in `requirements.txt`) the
  video is rendered inside the window on any Qt platform, Wayland included. If
  `python-mpv` or `libmpv` are missing, the app falls back to mpv as an external
  process attached with `--wid`: that one requires X11, and in that case alone
  the app switches automatically to the `xcb` Qt platform inside a Wayland
  session (which can be disabled with `./run.sh --wayland` or
  `YTEDIT_KEEP_WAYLAND=1`).
- YouTube URLs of the form `watch?v=…&list=RD…` are automatically generated
  *mixes* and effectively infinite: the analysis uses `--flat-playlist` and
  `--no-playlist` to finish in a few seconds instead of never finishing at all.
- The output codecs follow the destination container (x264/AAC for MP4 and MKV,
  VP9/Opus for WebM, the native codec for audio-only containers).
- Fast cutting without re-encoding cuts at the nearest keyframe: an exact start
  point needs precise cutting.
