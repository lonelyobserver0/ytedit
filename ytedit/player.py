import shutil, subprocess
from PySide6.QtCore import QObject, Signal

class MPVPlayer(QObject):
    message = Signal(str)
    def __init__(self, wid=None):
        super().__init__()
        self.wid = wid
        self.proc = None

    def available(self):
        return shutil.which("mpv") is not None

    def play(self, path):
        if not self.available():
            self.message.emit("mpv non trovato nel PATH.")
            return
        self.stop()
        args = ["mpv", "--force-window=yes", "--keep-open=no", path]
        self.proc = subprocess.Popen(args)
        self.message.emit(f"Riproduzione: {path}")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self.proc = None
