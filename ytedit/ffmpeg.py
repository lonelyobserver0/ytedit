"""Ispezione media via ffprobe e costruzione dei comandi FFmpeg.

Le funzioni `*_cmd` restituiscono liste di argomenti pronte per subprocess:
non eseguono nulla, così sono verificabili e mostrabili in anteprima.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

VIDEO_ENCODE = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p"]
AUDIO_ENCODE = ["-c:a", "aac", "-b:a", "192k"]

AUDIO_CODECS = {
    "mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
    "wav": ["-c:a", "pcm_s16le"],
    "flac": ["-c:a", "flac"],
    "m4a": ["-c:a", "aac", "-b:a", "192k"],
    "aac": ["-c:a", "aac", "-b:a", "192k"],
    "opus": ["-c:a", "libopus", "-b:a", "160k"],
    "ogg": ["-c:a", "libvorbis", "-q:a", "5"],
}


class FFmpegError(RuntimeError):
    """Errore di configurazione rilevato prima di lanciare FFmpeg."""


@dataclass
class MediaInfo:
    duration: float = 0.0
    has_video: bool = False
    has_audio: bool = False
    width: int = 0
    height: int = 0
    video_codec: str = ""
    audio_codec: str = ""
    probed: bool = False

    def encode_args(self, dst) -> list[str]:
        """Codec di uscita coerenti con le tracce presenti e col contenitore `dst`."""
        if not self.probed:
            return video_encode_for(dst) + audio_encode_for(dst)
        args: list[str] = []
        if self.has_video:
            args += video_encode_for(dst)
        if self.has_audio or not self.has_video:
            args += audio_encode_for(dst)
        return args


_info_cache: dict[tuple, MediaInfo] = {}


def _cache_key(path) -> tuple:
    try:
        st = Path(path).stat()
        return (str(path), st.st_mtime, st.st_size)
    except OSError:
        return (str(path), 0.0, 0)


def media_info(path, refresh: bool = False) -> MediaInfo:
    """Interroga ffprobe (con cache per path+mtime+dimensione)."""
    key = _cache_key(path)
    if not refresh and key in _info_cache:
        return _info_cache[key]

    info = MediaInfo()
    try:
        proc = subprocess.run(
            [FFPROBE, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout or "{}")
            info.probed = True
            try:
                info.duration = float(data.get("format", {}).get("duration") or 0.0)
            except (TypeError, ValueError):
                info.duration = 0.0
            for stream in data.get("streams", []):
                kind = stream.get("codec_type")
                if kind == "video" and stream.get("disposition", {}).get("attached_pic") != 1:
                    info.has_video = True
                    info.width = int(stream.get("width") or 0)
                    info.height = int(stream.get("height") or 0)
                    info.video_codec = stream.get("codec_name") or ""
                elif kind == "audio":
                    info.has_audio = True
                    info.audio_codec = info.audio_codec or (stream.get("codec_name") or "")
                if not info.duration:
                    try:
                        info.duration = float(stream.get("duration") or 0.0)
                    except (TypeError, ValueError):
                        pass
    except (OSError, ValueError, subprocess.SubprocessError):
        pass

    _info_cache[key] = info
    return info

# Codec accettati dai contenitori più comuni: serve a sapere quando `-c copy`
# è lecito e quando invece va forzata la ricodifica.
_CONTAINER_VIDEO = {
    ".webm": {"vp8", "vp9", "av1"},
    ".mp4": {"h264", "hevc", "mpeg4", "av1", "vp9"},
    ".m4v": {"h264", "hevc", "mpeg4"},
    ".mov": {"h264", "hevc", "mpeg4", "prores", "dnxhd"},
}
_CONTAINER_AUDIO = {
    ".webm": {"opus", "vorbis"},
    ".mp4": {"aac", "mp3", "ac3", "alac", "opus"},
    ".m4v": {"aac", "mp3", "alac"},
    ".m4a": {"aac", "alac"},
    ".mov": {"aac", "mp3", "pcm_s16le", "alac"},
    ".mp3": {"mp3"},
    ".flac": {"flac"},
    ".wav": {"pcm_s16le", "pcm_s24le", "pcm_f32le"},
    ".opus": {"opus"},
    ".ogg": {"vorbis", "opus", "flac"},
}
_AUDIO_ONLY_CONTAINERS = {".mp3", ".flac", ".wav", ".m4a", ".opus", ".ogg", ".aac"}


def can_copy_video(info: "MediaInfo", dst) -> bool:
    suffix = Path(dst).suffix.lower()
    if not info.probed or not info.has_video:
        return False
    if suffix in _AUDIO_ONLY_CONTAINERS:
        return False
    allowed = _CONTAINER_VIDEO.get(suffix)
    return True if allowed is None else info.video_codec in allowed


def can_copy_audio(info: "MediaInfo", dst) -> bool:
    suffix = Path(dst).suffix.lower()
    if not info.probed or not info.has_audio:
        return False
    allowed = _CONTAINER_AUDIO.get(suffix)
    return True if allowed is None else info.audio_codec in allowed


def video_encode_for(dst) -> list[str]:
    """x264 non è valido in WebM: lì serve VP9."""
    if Path(dst).suffix.lower() == ".webm":
        return ["-c:v", "libvpx-vp9", "-crf", "31", "-b:v", "0", "-pix_fmt", "yuv420p"]
    return VIDEO_ENCODE


def audio_encode_for(dst) -> list[str]:
    """AAC va bene in MP4/MKV ma non, ad esempio, in FLAC/WAV/WebM."""
    suffix = Path(dst).suffix.lower().lstrip(".")
    if suffix in AUDIO_CODECS:
        return AUDIO_CODECS[suffix]
    if suffix == "webm":
        return ["-c:a", "libopus", "-b:a", "160k"]
    return AUDIO_ENCODE


def parse_timestamp(value) -> float:
    """Accetta `SS`, `MM:SS`, `HH:MM:SS` con decimali; restituisce secondi."""
    text = str(value).strip().replace(",", ".")
    if not text:
        raise FFmpegError("Timestamp vuoto.")
    parts = text.split(":")
    if len(parts) > 3:
        raise FFmpegError(f"Timestamp non valido: {value}")
    total = 0.0
    for part in parts:
        part = part.strip() or "0"
        try:
            total = total * 60 + float(part)
        except ValueError:
            raise FFmpegError(f"Timestamp non valido: {value}") from None
    if total < 0:
        raise FFmpegError(f"Timestamp negativo: {value}")
    return total


def format_timestamp(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{int(hours):02d}:{int(minutes):02d}:{secs:06.3f}"


def _escape_filter_path(path) -> str:
    """Quota un path per un filtergraph (subtitles=filename='...')."""
    text = str(path).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{text}'"


def cut_cmd(src, dst, start, end, precise: bool = False) -> list[str]:
    """Taglia [start, end].

    Usa `-ss` in input (seek veloce) più `-t` con la durata calcolata: `-to`
    dopo `-i` sarebbe relativo al timeline post-seek e taglierebbe troppo.
    """
    start_s = parse_timestamp(start)
    end_s = parse_timestamp(end)
    if end_s <= start_s:
        raise FFmpegError("OUT deve essere maggiore di IN.")
    duration = end_s - start_s

    info = media_info(src)
    if info.probed and info.duration and start_s >= info.duration:
        raise FFmpegError(
            f"IN ({format_timestamp(start_s)}) oltre la durata del file "
            f"({format_timestamp(info.duration)})."
        )

    args = [FFMPEG, "-y", "-ss", format_timestamp(start_s), "-i", str(src),
            "-t", format_timestamp(duration)]
    if precise:
        return args + info.encode_args(dst) + [str(dst)]
    if info.probed:
        if info.has_video and not can_copy_video(info, dst):
            raise FFmpegError(
                f"Il codec video {info.video_codec or '?'} non è compatibile con "
                f"{Path(dst).suffix or 'questo contenitore'}: usa il taglio preciso."
            )
        if info.has_audio and not can_copy_audio(info, dst):
            raise FFmpegError(
                f"Il codec audio {info.audio_codec or '?'} non è compatibile con "
                f"{Path(dst).suffix or 'questo contenitore'}: usa il taglio preciso."
            )
    return args + ["-c", "copy", str(dst)]


def extract_audio_cmd(src, dst, codec: str = "flac") -> list[str]:
    args = AUDIO_CODECS.get(codec.lower().lstrip("."), AUDIO_CODECS["flac"])
    return [FFMPEG, "-y", "-i", str(src), "-vn", *args, str(dst)]


def transform_cmd(src, dst, width="", height="", rotate="none", volume="1.0",
                  fade_in="", fade_out="", subtitles=None) -> list[str]:
    """Scala / ruota / regola volume / dissolvenze / masterizza sottotitoli."""
    info = media_info(src)
    vf: list[str] = []
    af: list[str] = []

    width, height = str(width).strip(), str(height).strip()
    if width or height:
        if not (width and height):
            raise FFmpegError("Specifica sia larghezza sia altezza (usa -1 per il lato automatico).")
        vf.append(f"scale={width}:{height}")

    if rotate == "90":
        vf.append("transpose=1")
    elif rotate == "180":
        vf.append("transpose=1,transpose=1")
    elif rotate == "270":
        vf.append("transpose=2")

    if subtitles:
        if not Path(subtitles).exists():
            raise FFmpegError(f"File sottotitoli non trovato: {subtitles}")
        vf.append(f"subtitles=filename={_escape_filter_path(Path(subtitles).resolve())}")

    volume = str(volume).strip()
    if volume and volume not in ("1.0", "1", "1.00"):
        af.append(f"volume={volume}")

    fade_in, fade_out = str(fade_in).strip(), str(fade_out).strip()
    if fade_in:
        af.append(f"afade=t=in:st=0:d={parse_timestamp(fade_in)}")
    if fade_out:
        seconds = parse_timestamp(fade_out)
        if not info.duration:
            raise FFmpegError("Durata del file sconosciuta: impossibile calcolare il fade out.")
        af.append(f"afade=t=out:st={max(0.0, info.duration - seconds):.3f}:d={seconds}")

    args = [FFMPEG, "-y", "-i", str(src)]
    if not vf and not af:
        # Nessun filtro: se i codec entrano nel contenitore basta un remux,
        # invece di sprecare una passata di ricodifica.
        copy_ok = ((not info.has_video or can_copy_video(info, dst))
                   and (not info.has_audio or can_copy_audio(info, dst)))
        if copy_ok or not info.probed:
            return args + ["-c", "copy", str(dst)]
        return args + info.encode_args(dst) + [str(dst)]
    if vf:
        if info.probed and not info.has_video:
            raise FFmpegError("Il file non contiene video: filtri video non applicabili.")
        args += ["-vf", ",".join(vf)]
    if af:
        if info.probed and not info.has_audio:
            raise FFmpegError("Il file non contiene audio: filtri audio non applicabili.")
        args += ["-af", ",".join(af)]

    encode = []
    if vf:
        encode += video_encode_for(dst)
    elif info.has_video or not info.probed:
        encode += ["-c:v", "copy"] if can_copy_video(info, dst) else video_encode_for(dst)
    if af:
        encode += audio_encode_for(dst)
    elif info.has_audio or not info.probed:
        encode += ["-c:a", "copy"] if can_copy_audio(info, dst) else audio_encode_for(dst)
    return args + encode + [str(dst)]


def remove_section_cmd(src, dst, start, end) -> list[str]:
    """Rimuove l'intervallo [start, end] e ricuce le due parti rimanenti.

    Un solo passaggio con `trim`/`concat`: tagliare e riunire separatamente
    costringerebbe a file intermedi e a due ricodifiche.
    """
    start_s = parse_timestamp(start)
    end_s = parse_timestamp(end)
    if end_s <= start_s:
        raise FFmpegError("La fine della selezione deve superare l'inizio.")

    info = media_info(src)
    duration = info.duration
    if info.probed and duration:
        if start_s >= duration:
            raise FFmpegError(
                f"La selezione inizia oltre la fine del file "
                f"({format_timestamp(duration)})."
            )
        end_s = min(end_s, duration)
        if start_s <= 0 and end_s >= duration - 0.05:
            raise FFmpegError("La selezione copre tutto il file: non resterebbe nulla.")

    # Se la selezione tocca un estremo resta un solo spezzone: basta un taglio.
    if start_s <= 0:
        return cut_cmd(src, dst, format_timestamp(end_s),
                       format_timestamp(duration or end_s + 1), precise=True)
    if duration and end_s >= duration - 0.05:
        return cut_cmd(src, dst, "0", format_timestamp(start_s), precise=True)

    has_video = info.has_video or not info.probed
    has_audio = info.has_audio or not info.probed
    parts, labels = [], ""
    for index, (from_s, to_s) in enumerate(
            ((0.0, start_s), (end_s, duration or None))):
        if has_video:
            window = f"start={from_s:.3f}" + (f":end={to_s:.3f}" if to_s else "")
            parts.append(f"[0:v]trim={window},setpts=PTS-STARTPTS[v{index}]")
            labels += f"[v{index}]"
        if has_audio:
            window = f"start={from_s:.3f}" + (f":end={to_s:.3f}" if to_s else "")
            parts.append(f"[0:a]atrim={window},asetpts=PTS-STARTPTS[a{index}]")
            labels += f"[a{index}]"

    concat = (f"{labels}concat=n=2:v={1 if has_video else 0}:"
              f"a={1 if has_audio else 0}"
              + ("[outv]" if has_video else "") + ("[outa]" if has_audio else ""))
    args = [FFMPEG, "-y", "-i", str(src), "-filter_complex", ";".join(parts + [concat])]
    if has_video:
        args += ["-map", "[outv]", *video_encode_for(dst)]
    if has_audio:
        args += ["-map", "[outa]", *audio_encode_for(dst)]
    return args + [str(dst)]


def replace_audio_cmd(video, audio, dst) -> list[str]:
    return [FFMPEG, "-y", "-i", str(video), "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
            *audio_encode_for(dst), "-shortest", str(dst)]


def burn_subtitles_cmd(src, subtitles, dst) -> list[str]:
    """Masterizza i sottotitoli nel video (irreversibile, richiede ricodifica)."""
    info = media_info(src)
    if info.probed and not info.has_video:
        raise FFmpegError("Il file non contiene video.")
    if not Path(subtitles).exists():
        raise FFmpegError(f"File sottotitoli non trovato: {subtitles}")
    args = [FFMPEG, "-y", "-i", str(src),
            "-vf", f"subtitles=filename={_escape_filter_path(Path(subtitles).resolve())}",
            *video_encode_for(dst)]
    args += audio_encode_for(dst) if (info.has_audio or not info.probed) else []
    return args + [str(dst)]


def mux_subtitles_cmd(src, subtitles, dst) -> list[str]:
    """Aggiunge i sottotitoli come traccia separata (attivabile nel player)."""
    if not Path(subtitles).exists():
        raise FFmpegError(f"File sottotitoli non trovato: {subtitles}")
    codec = "mov_text" if Path(dst).suffix.lower() in (".mp4", ".m4v", ".mov") else "srt"
    return [FFMPEG, "-y", "-i", str(src), "-i", str(subtitles),
            "-map", "0", "-map", "1", "-c", "copy", "-c:s", codec,
            "-disposition:s:0", "default", str(dst)]


def write_concat_list(paths, list_path) -> Path:
    """Scrive la lista per il demuxer `concat` (path assoluti, apici raddoppiati)."""
    lines = []
    for path in paths:
        resolved = str(Path(path).resolve()).replace("'", "'\\''")
        lines.append(f"file '{resolved}'")
    list_path = Path(list_path)
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return list_path


def concat_copy_cmd(list_path, dst) -> list[str]:
    """Concatenazione senza ricodifica: richiede stessi codec e parametri."""
    return [FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
            "-c", "copy", str(dst)]


def concat_encode_cmd(paths, dst) -> list[str]:
    """Concatenazione con ricodifica: tollera sorgenti eterogenee."""
    paths = list(paths)
    if len(paths) < 2:
        raise FFmpegError("Servono almeno due file da unire.")
    infos = [media_info(p) for p in paths]
    has_video = all(i.has_video for i in infos)
    has_audio = all(i.has_audio for i in infos)
    if not has_video and not has_audio:
        raise FFmpegError("I file selezionati non condividono né video né audio.")

    args = [FFMPEG, "-y"]
    for path in paths:
        args += ["-i", str(path)]

    streams = ""
    for index in range(len(paths)):
        if has_video:
            streams += f"[{index}:v:0]"
        if has_audio:
            streams += f"[{index}:a:0]"
    labels = ("[outv]" if has_video else "") + ("[outa]" if has_audio else "")
    filtergraph = (f"{streams}concat=n={len(paths)}:"
                   f"v={1 if has_video else 0}:a={1 if has_audio else 0}{labels}")

    args += ["-filter_complex", filtergraph]
    if has_video:
        args += ["-map", "[outv]", *video_encode_for(dst)]
    if has_audio:
        args += ["-map", "[outa]", *audio_encode_for(dst)]
    return args + [str(dst)]
