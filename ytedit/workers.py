import subprocess, threading, re
from PySide6.QtCore import QThread, Signal

class ProcessWorker(QThread):
    output = Signal(str)
    progress = Signal(int)
    finished_ok = Signal(int, str)

    def __init__(self, args, cwd=None):
        super().__init__()
        self.args = args
        self.cwd = cwd
        self.proc = None
        self._stop = False

    def run(self):
        try:
            self.proc = subprocess.Popen(
                self.args, cwd=self.cwd, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1
            )
            last = ""
            for line in self.proc.stdout:
                if self._stop:
                    self.proc.terminate()
                    break
                line = line.rstrip()
                if line:
                    last = line
                    self.output.emit(line)
                    m = re.search(r'(\d+(?:\.\d+)?)%', line)
                    if m:
                        self.progress.emit(max(0, min(100, int(float(m.group(1))))))
            code = self.proc.wait()
            self.finished_ok.emit(code, last)
        except Exception as e:
            self.output.emit(f"ERROR: {e}")
            self.finished_ok.emit(-1, str(e))

    def stop(self):
        self._stop = True
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass
