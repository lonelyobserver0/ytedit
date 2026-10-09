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


def _number(value, default, name, low=None, high=None) -> float:
    """Legge un parametro numerico dell'interfaccia, vuoto = valore neutro."""
    text = str(value).strip().replace(",", ".")
    if not text:
        return default
    try:
        number = float(text)
    except ValueError:
        raise FFmpegError(f"{name}: '{value}' is not a number.") from None
    if (low is not None and number < low) or (high is not None and number > high):
        raise FFmpegError(f"{name} must be between {low:g} and {high:g}.")
    return number


def parse_timestamp(value) -> float:
    """Accetta `SS`, `MM:SS`, `HH:MM:SS` con decimali; restituisce secondi."""
    text = str(value).strip().replace(",", ".")
    if not text:
        raise FFmpegError("Empty timestamp.")
    parts = text.split(":")
    if len(parts) > 3:
        raise FFmpegError(f"Invalid timestamp: {value}")
    total = 0.0
    for part in parts:
        part = part.strip() or "0"
        try:
            total = total * 60 + float(part)
        except ValueError:
            raise FFmpegError(f"Invalid timestamp: {value}") from None
    if total < 0:
        raise FFmpegError(f"Negative timestamp: {value}")
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
        raise FFmpegError("OUT must be greater than IN.")
    duration = end_s - start_s

    info = media_info(src)
    if info.probed and info.duration and start_s >= info.duration:
        raise FFmpegError(
            f"IN ({format_timestamp(start_s)}) is past the end of the file "
            f"({format_timestamp(info.duration)})."
        )

    args = [FFMPEG, "-y", "-ss", format_timestamp(start_s), "-i", str(src),
            "-t", format_timestamp(duration)]
    if precise:
        return args + info.encode_args(dst) + [str(dst)]
    if info.probed:
        if info.has_video and not can_copy_video(info, dst):
            raise FFmpegError(
                f"The video codec {info.video_codec or '?'} is not compatible with "
                f"{Path(dst).suffix or 'this container'}: use the precise cut."
            )
        if info.has_audio and not can_copy_audio(info, dst):
            raise FFmpegError(
                f"The audio codec {info.audio_codec or '?'} is not compatible with "
                f"{Path(dst).suffix or 'this container'}: use the precise cut."
            )
    return args + ["-c", "copy", str(dst)]


def extract_audio_cmd(src, dst, codec: str = "flac") -> list[str]:
    args = AUDIO_CODECS.get(codec.lower().lstrip("."), AUDIO_CODECS["flac"])
    return [FFMPEG, "-y", "-i", str(src), "-vn", *args, str(dst)]


def crop_filter(crop) -> str:
    """`crop=w:h:x:y` da una quaterna (x, y, larghezza, altezza) dell'interfaccia."""
    x, y, w, h = (str(v).strip() for v in crop)
    if not (w or h or x or y):
        return ""
    if not (w and h):
        raise FFmpegError("Crop needs at least a width and a height.")
    x, y = x or "0", y or "0"
    for name, value, minimum in (("width", w, 1), ("height", h, 1), ("x", x, 0), ("y", y, 0)):
        if not value.isdigit() or int(value) < minimum:
            raise FFmpegError(
                f"Crop {name} must be a whole number of pixels, "
                f"{'greater than zero' if minimum else 'zero or more'}."
            )
    return f"crop={w}:{h}:{x}:{y}"


def eq_filter(brightness="", contrast="", saturation="", gamma="") -> str:
    """`eq=…` con le sole voci che si discostano dal neutro; "" se non serve."""
    parts = []
    for name, value, neutral, low, high in (
            ("brightness", brightness, 0.0, -1.0, 1.0),
            ("contrast", contrast, 1.0, -2.0, 4.0),
            ("saturation", saturation, 1.0, 0.0, 3.0),
            ("gamma", gamma, 1.0, 0.1, 10.0)):
        number = _number(value, neutral, name.capitalize(), low, high)
        if abs(number - neutral) > 1e-6:
            parts.append(f"{name}={number:g}")
    return "eq=" + ":".join(parts) if parts else ""


def transform_cmd(src, dst, width="", height="", rotate="none", volume="1.0",
                  fade_in="", fade_out="", subtitles=None, crop=None,
                  brightness="", contrast="", saturation="", gamma="") -> list[str]:
    """Ritaglia / scala / ruota / corregge il colore / volume / dissolvenze."""
    info = media_info(src)
    vf: list[str] = []
    af: list[str] = []

    if crop:
        # Prima di tutto: scalare e poi ritagliare darebbe un risultato diverso.
        filter_text = crop_filter(crop)
        if filter_text:
            vf.append(filter_text)

    width, height = str(width).strip(), str(height).strip()
    if width or height:
        if not (width and height):
            raise FFmpegError("Give both width and height (use -1 for the automatic side).")
        vf.append(f"scale={width}:{height}")

    if rotate == "90":
        vf.append("transpose=1")
    elif rotate == "180":
        vf.append("transpose=1,transpose=1")
    elif rotate == "270":
        vf.append("transpose=2")

    colour = eq_filter(brightness, contrast, saturation, gamma)
    if colour:
        vf.append(colour)

    if subtitles:
        if not Path(subtitles).exists():
            raise FFmpegError(f"Subtitle file not found: {subtitles}")
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
            raise FFmpegError("File duration unknown: cannot work out the fade out.")
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
            raise FFmpegError("The file holds no video: video filters do not apply.")
        args += ["-vf", ",".join(vf)]
    if af:
        if info.probed and not info.has_audio:
            raise FFmpegError("The file holds no audio: audio filters do not apply.")
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


def normalize_segments(segments, duration=0.0) -> list[tuple]:
    """Ordina, scarta i vuoti, fonde quelli che si toccano, taglia alla durata.

    Gli intervalli arrivano da una lista costruita a mano dall'utente: possono
    sovrapporsi, ripetersi o sforare la fine del file. Il resto del modulo dà
    per scontato che siano disgiunti e in ordine.
    """
    windows = []
    for first, second in segments:
        begin = parse_timestamp(first) if isinstance(first, str) else float(first)
        finish = parse_timestamp(second) if isinstance(second, str) else float(second)
        if duration:
            begin, finish = min(begin, duration), min(finish, duration)
        if finish - begin > 0.001:
            windows.append([begin, finish])
    windows.sort()

    merged: list[list] = []
    for begin, finish in windows:
        if merged and begin <= merged[-1][1] + 0.001:
            merged[-1][1] = max(merged[-1][1], finish)
        else:
            merged.append([begin, finish])
    return [(begin, finish) for begin, finish in merged]


def invert_segments(segments, duration=0.0) -> list[tuple]:
    """Il complemento su [0, durata]: cosa resta togliendo gli intervalli.

    Con durata ignota l'ultima finestra resta aperta (`None`): si taglia dalla
    fine dell'ultimo intervallo in poi, senza sapere dove sia la fine.
    """
    gaps: list[tuple] = []
    cursor = 0.0
    for begin, finish in segments:
        if begin - cursor > 0.001:
            gaps.append((cursor, begin))
        cursor = max(cursor, finish)
    if not duration:
        gaps.append((cursor, None))
    elif duration - cursor > 0.001:
        gaps.append((cursor, duration))
    return gaps


def _windows_cmd(src, dst, windows, info=None) -> list[str]:
    """Tiene le finestre indicate e le ricuce in un solo passaggio FFmpeg.

    Una finestra sola non ha niente da ricucire: è un taglio, e il taglio sa
    già gestire il caso in cui la fine non sia nota.
    """
    info = info or media_info(src)
    if not windows:
        raise FFmpegError("Nothing would be left: no segment to keep.")

    if len(windows) == 1:
        begin, finish = windows[0]
        if finish is None:
            return ([FFMPEG, "-y", "-ss", format_timestamp(begin), "-i", str(src)]
                    + info.encode_args(dst) + [str(dst)])
        return cut_cmd(src, dst, format_timestamp(begin), format_timestamp(finish), precise=True)

    has_video = info.has_video or not info.probed
    has_audio = info.has_audio or not info.probed
    parts, labels = [], ""
    for index, (begin, finish) in enumerate(windows):
        window = f"start={begin:.3f}" + (f":end={finish:.3f}" if finish is not None else "")
        if has_video:
            parts.append(f"[0:v]trim={window},setpts=PTS-STARTPTS[v{index}]")
            labels += f"[v{index}]"
        if has_audio:
            parts.append(f"[0:a]atrim={window},asetpts=PTS-STARTPTS[a{index}]")
            labels += f"[a{index}]"

    concat = (f"{labels}concat=n={len(windows)}:v={1 if has_video else 0}:"
              f"a={1 if has_audio else 0}"
              + ("[outv]" if has_video else "") + ("[outa]" if has_audio else ""))
    args = [FFMPEG, "-y", "-i", str(src), "-filter_complex", ";".join(parts + [concat])]
    if has_video:
        args += ["-map", "[outv]", *video_encode_for(dst)]
    if has_audio:
        args += ["-map", "[outa]", *audio_encode_for(dst)]
    return args + [str(dst)]


def keep_segments_cmd(src, dst, segments) -> list[str]:
    """Tiene solo gli intervalli indicati, nell'ordine del file."""
    info = media_info(src)
    windows = normalize_segments(segments, info.duration)
    if not windows:
        raise FFmpegError("No valid segment selected.")
    return _windows_cmd(src, dst, windows, info)


def remove_segments_cmd(src, dst, segments) -> list[str]:
    """Elimina gli intervalli indicati e ricuce quello che resta."""
    info = media_info(src)
    windows = normalize_segments(segments, info.duration)
    if not windows:
        raise FFmpegError("No valid segment selected.")
    if info.probed and info.duration and windows[0][0] <= 0 and windows[-1][1] >= info.duration - 0.05:
        if len(windows) == 1:
            raise FFmpegError("The selection covers the whole file: nothing would be left.")
    keep = invert_segments(windows, info.duration)
    if not keep:
        raise FFmpegError("The selection covers the whole file: nothing would be left.")
    return _windows_cmd(src, dst, keep, info)


def remove_section_cmd(src, dst, start, end) -> list[str]:
    """Rimuove l'intervallo [start, end] e ricuce le due parti rimanenti."""
    start_s = parse_timestamp(start)
    end_s = parse_timestamp(end)
    if end_s <= start_s:
        raise FFmpegError("The end of the selection must come after its start.")
    info = media_info(src)
    if info.probed and info.duration and start_s >= info.duration:
        raise FFmpegError(
            f"The selection starts past the end of the file "
            f"({format_timestamp(info.duration)})."
        )
    return remove_segments_cmd(src, dst, [(start_s, end_s)])


def replace_audio_cmd(video, audio, dst) -> list[str]:
    return [FFMPEG, "-y", "-i", str(video), "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
            *audio_encode_for(dst), "-shortest", str(dst)]


def burn_subtitles_cmd(src, subtitles, dst) -> list[str]:
    """Masterizza i sottotitoli nel video (irreversibile, richiede ricodifica)."""
    info = media_info(src)
    if info.probed and not info.has_video:
        raise FFmpegError("The file holds no video.")
    if not Path(subtitles).exists():
        raise FFmpegError(f"Subtitle file not found: {subtitles}")
    args = [FFMPEG, "-y", "-i", str(src),
            "-vf", f"subtitles=filename={_escape_filter_path(Path(subtitles).resolve())}",
            *video_encode_for(dst)]
    args += audio_encode_for(dst) if (info.has_audio or not info.probed) else []
    return args + [str(dst)]


def mux_subtitles_cmd(src, subtitles, dst) -> list[str]:
    """Aggiunge i sottotitoli come traccia separata (attivabile nel player)."""
    if not Path(subtitles).exists():
        raise FFmpegError(f"Subtitle file not found: {subtitles}")
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
        raise FFmpegError("At least two files are needed to merge.")
    infos = [media_info(p) for p in paths]
    has_video = all(i.has_video for i in infos)
    has_audio = all(i.has_audio for i in infos)
    if not has_video and not has_audio:
        raise FFmpegError("The selected files share neither video nor audio.")

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


def frame_cmd(src, dst, position) -> list[str]:
    """Salva un solo fotogramma come immagine.

    `-ss` prima di `-i` cerca saltando la decodifica: con `-accurate_seek`
    attivo di default il fotogramma è comunque quello giusto, non il keyframe.
    """
    seconds = parse_timestamp(position)
    info = media_info(src)
    if info.probed and not info.has_video:
        raise FFmpegError("The file holds no video: there is no frame to save.")
    if info.probed and info.duration and seconds >= info.duration:
        raise FFmpegError(
            f"Position {format_timestamp(seconds)} is past the end of the file "
            f"({format_timestamp(info.duration)})."
        )
    args = [FFMPEG, "-y", "-ss", format_timestamp(seconds), "-i", str(src),
            "-frames:v", "1", "-update", "1"]
    if Path(dst).suffix.lower() in (".jpg", ".jpeg"):
        args += ["-q:v", "2"]
    return args + [str(dst)]


def atempo_chain(factor: float) -> list[float]:
    """`atempo` accetta un fattore per volta: oltre i limiti si incatena.

    Le versioni storiche del filtro stanno fra 0.5 e 2.0; scomporre funziona
    ovunque e non costa nulla, quindi non si va a chiedere la versione.
    """
    chain = []
    remaining = float(factor)
    while remaining > 2.0:
        chain.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        chain.append(0.5)
        remaining /= 0.5
    chain.append(remaining)
    return chain


def speed_cmd(src, dst, factor, keep_audio: bool = True) -> list[str]:
    """Cambia la velocità di riproduzione: >1 accelera, <1 rallenta.

    `setpts` riscrive i tempi di presentazione, `atempo` allunga o accorcia
    l'audio senza spostarne l'intonazione.
    """
    factor = _number(factor, 1.0, "Speed", 0.1, 10.0)
    if abs(factor - 1.0) < 1e-6:
        raise FFmpegError("Speed 1× changes nothing: pick another factor.")

    info = media_info(src)
    has_video = info.has_video or not info.probed
    has_audio = info.has_audio and keep_audio
    if not has_video and not has_audio:
        raise FFmpegError("Nothing to speed up: no video, and the audio is muted.")

    filters = []
    if has_video:
        filters.append(f"[0:v]setpts={1 / factor:.6f}*PTS[v]")
    if has_audio:
        chain = ",".join(f"atempo={step:.6f}" for step in atempo_chain(factor))
        filters.append(f"[0:a]{chain}[a]")

    args = [FFMPEG, "-y", "-i", str(src), "-filter_complex", ";".join(filters)]
    if has_video:
        args += ["-map", "[v]", *video_encode_for(dst)]
    if has_audio:
        args += ["-map", "[a]", *audio_encode_for(dst)]
    elif has_video:
        args += ["-an"]
    return args + [str(dst)]


def animation_cmd(src, dst, start, end, fps=12, width=480) -> list[str]:
    """Esporta l'intervallo come GIF o WebP animata.

    Per la GIF serve una tavolozza costruita sulle immagini vere: le 256 tinte
    di default sono le stesse per qualsiasi video e il risultato si sporca.
    `split` calcola la tavolozza e la applica in un passaggio solo.
    """
    start_s = parse_timestamp(start)
    end_s = parse_timestamp(end)
    if end_s <= start_s:
        raise FFmpegError("OUT must be greater than IN.")
    fps = int(_number(fps, 12, "Frame rate", 1, 50))
    width = int(_number(width, 480, "Width", 16, 1920))

    info = media_info(src)
    if info.probed and not info.has_video:
        raise FFmpegError("The file holds no video: there is nothing to animate.")

    suffix = Path(dst).suffix.lower()
    base = [FFMPEG, "-y", "-ss", format_timestamp(start_s),
            "-t", format_timestamp(end_s - start_s), "-i", str(src), "-an"]
    scale = f"fps={fps},scale={width}:-1:flags=lanczos"

    if suffix == ".webp":
        return base + ["-vf", scale, "-c:v", "libwebp", "-lossless", "0",
                       "-q:v", "75", "-loop", "0", str(dst)]
    if suffix != ".gif":
        raise FFmpegError(
            f"Unsupported animation format: {suffix or 'no extension'} (use .gif or .webp)."
        )
    graph = (f"[0:v]{scale},split[a][b];"
             f"[a]palettegen=stats_mode=diff[p];"
             f"[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle")
    return base + ["-filter_complex", graph, "-loop", "0", str(dst)]
