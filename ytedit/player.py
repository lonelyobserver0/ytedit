"""Player MPV: embedding nella finestra Qt e controllo via socket IPC."""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QGuiApplication


_URL_RE = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.IGNORECASE)


def is_url(target) -> bool:
    return bool(_URL_RE.match(str(target).strip()))


def ytdl_path():
    """mpv cerca yt-dlp nel PATH: il nostro sta nel venv, glielo indichiamo."""
    candidate = Path(sys.executable).with_name("yt-dlp")
    if candidate.exists():
        return str(candidate)
    return shutil.which("yt-dlp")


class MPVPlayer(QObject):
    message = Signal(str)
    stopped = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proc = None
        self.path = None
        self._socket_path = None
        self._request_id = 0

    def available(self) -> bool:
        return shutil.which("mpv") is not None

    def can_embed(self) -> bool:
        """`--wid` richiede una finestra X11: sotto Wayland nativo non funziona."""
        app = QGuiApplication.instance()
        return bool(app) and app.platformName() in ("xcb", "windows")

    def is_running(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    def play(self, path, wid=None, start=None, ytdl_format=None):
        """`path` può essere un file locale o un URL: mpv lo apre in streaming
        passando da yt-dlp, senza scaricare nulla su disco."""
        if not self.available():
            self.message.emit("mpv not found in the PATH.")
            return False
        self.stop()

        self._socket_path = os.path.join(
            tempfile.gettempdir(), f"ytedit-mpv-{uuid.uuid4().hex}.sock"
        )
        args = ["mpv", "--keep-open=yes", "--osc=yes",
                f"--input-ipc-server={self._socket_path}"]
        if is_url(path):
            ytdl = ytdl_path()
            if ytdl:
                args.append(f"--script-opts=ytdl_hook-ytdl_path={ytdl}")
            if ytdl_format:
                args.append(f"--ytdl-format={ytdl_format}")
        if wid is not None and self.can_embed():
            args.append(f"--wid={int(wid)}")
        else:
            args.append("--force-window=yes")
            if wid is not None:
                self.message.emit(
                    "The embedded preview is not available on this platform "
                    "(X11 is needed): mpv opens in a separate window."
                )
        if start:
            args.append(f"--start={start}")
        args.append(str(path))

        try:
            self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL)
        except OSError as exc:
            self.message.emit(f"Could not start mpv: {exc}")
            return False

        self.path = str(path)
        self.message.emit(f"Playing: {path}")
        return True

    def _command(self, *cmd):
        """Invia un comando JSON IPC; None se mpv non risponde."""
        if not self.is_running() or not self._socket_path:
            return None
        self._request_id += 1
        payload = json.dumps({"command": list(cmd), "request_id": self._request_id})
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                    sock.settimeout(0.5)
                    sock.connect(self._socket_path)
                    sock.sendall(payload.encode() + b"\n")
                    buffer = b""
                    while b"\n" in buffer or not buffer:
                        chunk = sock.recv(4096)
                        if not chunk:
                            break
                        buffer += chunk
                        for raw in buffer.split(b"\n"):
                            if not raw.strip():
                                continue
                            try:
                                reply = json.loads(raw)
                            except ValueError:
                                continue
                            if reply.get("request_id") == self._request_id:
                                return reply
                    return None
            except (OSError, socket.timeout):
                time.sleep(0.05)  # il socket appare qualche istante dopo l'avvio
        return None

    def get_property(self, name):
        reply = self._command("get_property", name)
        if reply and reply.get("error") == "success":
            return reply.get("data")
        return None

    def time_pos(self):
        value = self.get_property("time-pos")
        return float(value) if isinstance(value, (int, float)) else None

    def duration(self):
        value = self.get_property("duration")
        return float(value) if isinstance(value, (int, float)) else None

    def toggle_pause(self):
        self._command("cycle", "pause")

    def seek(self, seconds, mode="absolute"):
        self._command("seek", float(seconds), mode)

    def stop(self):
        if self.is_running():
            try:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            except OSError:
                pass
        self.proc = None
        self.path = None
        if self._socket_path:
            try:
                os.unlink(self._socket_path)
            except OSError:
                pass
            self._socket_path = None
        self.stopped.emit()
