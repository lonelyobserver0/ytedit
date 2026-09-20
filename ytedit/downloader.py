"""Download via yt-dlp in un processo separato."""
import re
import subprocess
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QThread, Signal

# Marcatore per riconoscere senza ambiguità il path finale stampato da yt-dlp.
FILE_SENTINEL = "@@YTEDIT_FILE@@"
_PERCENT_RE = re.compile(r"\[download\]\s+(\d+(?:\.\d+)?)%")


def build_format(quality: str, audio_only: bool = False) -> str:
    """Traduce la scelta dell'interfaccia in un selettore -f di yt-dlp."""
    if audio_only:
        return "bestaudio/best"
    height = quality.rstrip("p") if quality.endswith("p") and quality[:-1].isdigit() else ""
    if not height:
        return "bestvideo+bestaudio/best"
    return f"bestvideo[height<={height}]+bestaudio/best[height<={height}]"


def build_command(url, output_dir, fmt="bestvideo+bestaudio/best", audio_only=False,
                  subtitles=False, container="", sub_langs="all",
                  audio_format="mp3", extra_args=None, playlist=False, section=None):
    """Riga di comando yt-dlp completa (usata anche per l'anteprima).

    Senza `--no-playlist` un URL come `watch?v=…&list=RD…` scarica l'intero mix
    YouTube, che è di fatto infinito.
    """
    if playlist:
        template = str(Path(output_dir) / "%(playlist_title)s" /
                       "%(playlist_index)03d - %(title)s.%(ext)s")
    elif section:
        # Nome distinto: il segmento non deve sovrascrivere il video intero.
        template = str(Path(output_dir) / "%(title)s [%(section_start)s-%(section_end)s].%(ext)s")
    else:
        template = str(Path(output_dir) / "%(title)s.%(ext)s")
    args = [
        sys.executable, "-m", "yt_dlp",
        "--newline", "--progress", "--no-colors",
        "--yes-playlist" if playlist else "--no-playlist",
        "-f", "bestaudio/best" if audio_only else fmt,
        "-o", template,
        "--print", f"after_move:{FILE_SENTINEL}%(filepath)s",
    ]
    if audio_only:
        args += ["-x", "--audio-format", audio_format, "--audio-quality", "0"]
    elif container:
        args += ["--merge-output-format", container.lower()]
    if subtitles:
        args += ["--write-subs", "--write-auto-subs", "--sub-langs", sub_langs or "all"]
    if section:
        # Scarica solo l'intervallo scelto, senza prendere tutto il video.
        start, end = section
        args += ["--download-sections", f"*{start}-{end}", "--force-keyframes-at-cuts"]
    return args + list(extra_args or []) + [url]


class YTDLPWorker(QThread):
    line = Signal(str)
    progress = Signal(int)
    filepath = Signal(str)
    result = Signal(object)
    error = Signal(str)

    def __init__(self, url, output_dir, fmt="bestvideo+bestaudio/best",
                 audio_only=False, subtitles=False, container="",
                 sub_langs="all", audio_format="mp3", extra_args=None,
                 playlist=False, section=None, parent=None):
        super().__init__(parent)
        self.url = url
        self.output_dir = output_dir
        self.fmt = fmt
        self.audio_only = audio_only
        self.subtitles = subtitles
        self.container = container
        self.sub_langs = sub_langs or "all"
        self.audio_format = audio_format
        self.extra_args = list(extra_args or [])
        self.playlist = playlist
        self.section = section
        self.proc = None
        self._stop = False

    def command(self):
        return build_command(
            self.url, self.output_dir, self.fmt, self.audio_only, self.subtitles,
            self.container, self.sub_langs, self.audio_format, self.extra_args,
            self.playlist, self.section,
        )

    def run(self):
        args = self.command()
        try:
            self.proc = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
        except OSError as exc:
            self.error.emit(str(exc))
            return

        out = []
        final_path = ""
        try:
            for raw in self.proc.stdout:
                if self._stop:
                    break
                line = raw.rstrip()
                if not line:
                    continue
                if line.startswith(FILE_SENTINEL):
                    final_path = line[len(FILE_SENTINEL):].strip()
                    self.line.emit(f"File: {final_path}")
                    self.filepath.emit(final_path)
                    continue
                out.append(line)
                self.line.emit(line)
                match = _PERCENT_RE.search(line)
                if match:
                    self.progress.emit(max(0, min(100, int(float(match.group(1))))))
        except (OSError, ValueError):
            pass
        except Exception:
            self.error.emit("Errore imprevisto nel download:\n" + traceback.format_exc())
        finally:
            if self.proc.stdout:
                self.proc.stdout.close()

        code = self.proc.wait()
        if self._stop:
            self.error.emit("Download interrotto.")
        elif code == 0:
            self.result.emit(final_path)
        else:
            self.error.emit("\n".join(out[-30:]) or f"yt-dlp uscito con codice {code}")

    def stop(self):
        self._stop = True
        if not self.proc or self.proc.poll() is not None:
            return
        try:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        except OSError:
            pass


def analyze_command(url, playlist=False):
    """`--flat-playlist` evita di estrarre ogni video di una playlist: l'analisi
    di un mix (`list=RD…`) altrimenti non termina."""
    return [sys.executable, "-m", "yt_dlp", "--dump-single-json",
            "--skip-download", "--no-colors", "--flat-playlist",
            "--yes-playlist" if playlist else "--no-playlist", url]


class AnalyzeWorker(QThread):
    """`--dump-single-json` fuori dal thread GUI, così l'interfaccia non si blocca."""
    result = Signal(object)
    error = Signal(str)
    line = Signal(str)

    def __init__(self, url, playlist=False, parent=None):
        super().__init__(parent)
        self.url = url
        self.playlist = playlist
        self.proc = None
        self._stop = False

    def run(self):
        # Nessun errore deve restare muto: qualunque eccezione finisce nel log.
        try:
            self._analyze()
        except Exception:
            self.error.emit("Errore imprevisto durante l'analisi:\n" + traceback.format_exc())

    def _analyze(self):
        import json
        try:
            self.proc = subprocess.Popen(
                analyze_command(self.url, self.playlist),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            out, err = self.proc.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            self.stop()
            self.error.emit(
                "Analisi scaduta dopo 120 s. Se l'URL contiene '&list=' prova a "
                "rimuovere la parte della playlist, oppure attiva 'Intera playlist'."
            )
            return
        except OSError as exc:
            self.error.emit(str(exc))
            return
        if self._stop:
            return
        # Gli avvisi di yt-dlp sono utili anche quando l'analisi riesce.
        for warning in (err or "").strip().splitlines():
            if warning.strip():
                self.line.emit(warning.strip())
        if self.proc.returncode:
            self.error.emit((err or "").strip()
                            or f"yt-dlp uscito con codice {self.proc.returncode}")
            return
        if not (out or "").strip():
            self.error.emit("yt-dlp non ha restituito alcun dato (uscita vuota).")
            return
        try:
            data = json.loads(out)
        except ValueError as exc:
            self.error.emit(f"Risposta yt-dlp non leggibile ({exc}). "
                            f"Inizio della risposta: {out[:200]!r}")
            return
        if not isinstance(data, dict):
            self.error.emit(f"yt-dlp ha restituito {type(data).__name__} invece di un oggetto JSON.")
            return
        self.result.emit(data)

    def stop(self):
        self._stop = True
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.kill()
            except OSError:
                pass
