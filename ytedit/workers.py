"""Esecuzione di processi esterni (FFmpeg) con progresso reale."""
import re
import subprocess
import traceback

from PySide6.QtCore import QThread, Signal

from .ffmpeg import FFMPEG, parse_timestamp

# Righe di `-progress pipe:1`: `chiave=valore` in minuscolo, senza spazi.
# Alimentano la barra e non vanno nel log.
_PROGRESS_LINE_RE = re.compile(r"^[a-z0-9_]+=")
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)%")


class ProcessWorker(QThread):
    output = Signal(str)
    progress = Signal(int)
    finished_ok = Signal(int, str)

    def __init__(self, args, cwd=None, total_duration=0.0, parent=None):
        super().__init__(parent)
        self.args = self._with_progress(list(args))
        self.cwd = cwd
        self.total_duration = float(total_duration or 0.0)
        self.proc = None
        self._stop = False
        self._last_progress = 0
        # True se leggiamo `-progress`: allora ignoriamo le percentuali nei log
        # (x264 ne stampa diverse a fine codifica) per non far saltare la barra.
        self._structured_progress = "-progress" in self.args

    @staticmethod
    def _with_progress(args):
        """FFmpeg non stampa percentuali: gli chiediamo `-progress` su stdout."""
        if not args or "-progress" in args:
            return args
        if args[0] != FFMPEG and not str(args[0]).endswith("ffmpeg"):
            return args
        return [args[0], "-hide_banner", "-nostats", "-progress", "pipe:1", *args[1:]]

    def run(self):
        try:
            self.proc = subprocess.Popen(
                self.args, cwd=self.cwd, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1,
            )
        except OSError as exc:
            self.output.emit(f"ERRORE: {exc}")
            self.finished_ok.emit(-1, str(exc))
            return

        last = ""
        try:
            for raw in self.proc.stdout:
                if self._stop:
                    break
                line = raw.rstrip()
                if not line:
                    continue
                if self._handle_progress(line):
                    continue
                last = line
                self.output.emit(line)
        except (OSError, ValueError):
            pass
        except Exception:
            self.output.emit("ERRORE imprevisto:\n" + traceback.format_exc())
        finally:
            if self.proc.stdout:
                self.proc.stdout.close()

        code = self.proc.wait()
        if self._stop:
            self.finished_ok.emit(-2, "Operazione interrotta.")
        else:
            if code == 0:
                self._emit_progress(100)
            self.finished_ok.emit(code, last)

    def _emit_progress(self, value: int):
        """La barra non torna mai indietro: evita sfarfallii sui valori fuori ordine."""
        value = max(0, min(100, value))
        if value >= self._last_progress:
            self._last_progress = value
            self.progress.emit(value)

    def _handle_progress(self, line) -> bool:
        """True se la riga è un aggiornamento di progresso (da non loggare)."""
        if self._structured_progress and _PROGRESS_LINE_RE.match(line):
            key, _, value = line.partition("=")
            value = value.strip()
            if key == "progress" and value == "end":
                self._emit_progress(100)
            elif key == "out_time" and self.total_duration > 0 and value != "N/A":
                try:
                    self._emit_progress(int(parse_timestamp(value) / self.total_duration * 100))
                except Exception:
                    pass
            return True

        if not self._structured_progress:
            match = _PERCENT_RE.search(line)
            if match:
                self._emit_progress(int(float(match.group(1))))
        return False

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
