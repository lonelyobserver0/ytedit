import json, sys
from PySide6.QtCore import QThread, Signal

class YTDLPWorker(QThread):
    line = Signal(str)
    result = Signal(object)
    error = Signal(str)

    def __init__(self, url, output_dir, fmt="bestvideo+bestaudio/best",
                 audio_only=False, subtitles=False):
        super().__init__()
        self.url = url
        self.output_dir = output_dir
        self.fmt = fmt
        self.audio_only = audio_only
        self.subtitles = subtitles
        self.proc = None

    def run(self):
        try:
            if self.audio_only:
                fmt = "bestaudio/best"
            else:
                fmt = self.fmt
            args = [
                sys.executable, "-m", "yt_dlp",
                "--newline", "--progress",
                "-f", fmt,
                "-o", f"{self.output_dir}/%(title)s.%(ext)s",
                "--print", "after_move:filepath",
            ]
            if self.audio_only:
                args += ["-x", "--audio-format", "mp3", "--audio-quality", "0"]
            if self.subtitles:
                args += ["--write-subs", "--sub-langs", "all"]
            args += [self.url]
            import subprocess
            self.proc = subprocess.Popen(args, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, text=True)
            out = []
            for line in self.proc.stdout:
                line = line.rstrip()
                out.append(line)
                self.line.emit(line)
            code = self.proc.wait()
            if code == 0:
                self.result.emit("\n".join(out))
            else:
                self.error.emit("\n".join(out[-30:]))
        except Exception as e:
            self.error.emit(str(e))

    def stop(self):
        if self.proc:
            self.proc.terminate()
