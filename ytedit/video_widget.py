"""Player video integrato: libmpv disegnata dentro un widget OpenGL di Qt.

A differenza dell'approccio con `--wid`, che richiede una finestra X11, qui i
fotogrammi vengono renderizzati nel contesto OpenGL del widget: funziona anche
su Wayland nativo e il video non può finire in una finestra separata.
"""
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QOpenGLContext, QPainter, QPen
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget

from . import theme

os.environ.setdefault("LC_NUMERIC", "C")  # libmpv pretende la locale C

try:
    import mpv as _mpv
except (ImportError, OSError) as exc:  # libmpv assente o non caricabile
    _mpv = None
    _IMPORT_ERROR = str(exc)
else:
    _IMPORT_ERROR = ""


def is_available() -> bool:
    return _mpv is not None


def unavailable_reason() -> str:
    return _IMPORT_ERROR or "python-mpv non installato"


def _get_proc_address(_ctx, name):
    """libmpv chiede gli indirizzi delle funzioni OpenGL al contesto di Qt."""
    context = QOpenGLContext.currentContext()
    if context is None:
        return 0
    if isinstance(name, bytes):
        name = name.decode("utf-8")
    return int(context.getProcAddress(name))


class VideoWidget(QOpenGLWidget):
    """Superficie video integrata, con la stessa API del player esterno."""

    message = Signal(str)
    stopped = Signal()
    _frame_ready = Signal()

    def __init__(self, parent=None, ytdl_path=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)

        self.path = None
        self.frames_rendered = 0     # diagnostica: quante volte abbiamo disegnato
        self._render_context = None
        self._pending = None         # riproduzione chiesta prima del contesto GL
        self._destroyed = False
        # Il callback ctypes va tenuto vivo: se lo raccoglie il GC, libmpv aborta.
        self._proc_address_cb = _mpv.MpvGlGetProcAddressFn(_get_proc_address)

        options = {
            "vo": "libmpv",
            "hwdec": "auto-safe",
            "keep_open": "yes",
            "osc": True,          # barra di avanzamento dentro il widget
            "input_default_bindings": True,
            "input_vo_keyboard": True,
            "ytdl": True,
        }
        if ytdl_path:
            options["script_opts"] = f"ytdl_hook-ytdl_path={ytdl_path}"
        self.mpv = _mpv.MPV(log_handler=self._log, **options)
        self._frame_ready.connect(self.update, Qt.QueuedConnection)

    # ------------------------------------------------------------ OpenGL

    def initializeGL(self):
        try:
            self._render_context = _mpv.MpvRenderContext(
                self.mpv, "opengl",
                opengl_init_params={"get_proc_address": self._proc_address_cb},
            )
        except Exception as exc:  # contesto GL inadatto: meglio dirlo
            self.message.emit(f"Impossibile inizializzare il rendering video: {exc}")
            return
        # Arriva dal thread di rendering di mpv: rimbalza sul thread GUI.
        self._render_context.update_cb = self._frame_ready.emit
        if self._pending is not None:
            pending, self._pending = self._pending, None
            self._start(*pending)

    def paintGL(self):
        if self.path is None or self._render_context is None or self._destroyed:
            self._paint_placeholder()
            return
        ratio = self.devicePixelRatioF()
        self._render_context.render(flip_y=True, opengl_fbo={
            "w": int(self.width() * ratio),
            "h": int(self.height() * ratio),
            "fbo": self.defaultFramebufferObject(),
        })
        self.frames_rendered += 1
        self._paint_frame()

    def _paint_frame(self):
        """Filetto attorno all'immagine: separa il visore dal pannello."""
        painter = QPainter(self)
        painter.setPen(QPen(QColor(theme.current().edge), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.end()

    def _paint_placeholder(self):
        """Schermo vuoto: dice cosa fare, invece di restare nero e muto."""
        painter = QPainter(self)
        tavolozza = theme.current()
        painter.fillRect(self.rect(), QColor(tavolozza.viewer))
        painter.setPen(QColor(tavolozza.mute))
        painter.setFont(theme.ui_font(11))
        painter.drawText(self.rect(), Qt.AlignCenter,
                         "Incolla un URL e premi Analizza,\noppure apri un file.")
        painter.setPen(QPen(QColor(tavolozza.edge), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.end()

    # ------------------------------------------------------- riproduzione

    def available(self) -> bool:
        return True

    def can_embed(self) -> bool:
        return True

    def is_running(self) -> bool:
        return bool(self.path) and not self._destroyed

    def play(self, path, wid=None, start=None, ytdl_format=None):
        """`wid` è ignorato: il video è già dentro questo widget."""
        if self._destroyed:
            return False
        if self._render_context is None:
            # QOpenGLWidget crea il contesto al primo disegno: rimandiamo,
            # altrimenti libmpv fallisce con "No render context set".
            self._pending = (path, start, ytdl_format)
            self.path = str(path)
            self.update()
            return True
        return self._start(path, start, ytdl_format)

    def _start(self, path, start=None, ytdl_format=None):
        try:
            self.mpv["ytdl-format"] = ytdl_format or "bestvideo+bestaudio/best"
            self.mpv["start"] = str(start) if start else "0"
            self.mpv.play(str(path))
            self.mpv.pause = False
        except Exception as exc:
            self.message.emit(f"Riproduzione fallita: {exc}")
            return False
        self.path = str(path)
        self.message.emit(f"Riproduzione: {path}")
        return True

    def toggle_pause(self):
        if self.is_running():
            self.mpv.pause = not self.mpv.pause

    def seek(self, seconds, mode="absolute"):
        if self.is_running():
            try:
                # precision="exact": senza, mpv salta al keyframe più vicino e
                # i punti IN/OUT non corrisponderebbero a quanto si vede.
                self.mpv.seek(float(seconds), reference=mode, precision="exact")
            except Exception as exc:
                self.message.emit(f"Seek fallito: {exc}")

    def _property(self, name):
        """Le proprietà runtime si leggono come attributi: `mpv["x"]` accede
        alle *opzioni*, che per time-pos/duration non esistono."""
        if not self.is_running():
            return None
        try:
            value = getattr(self.mpv, name.replace("-", "_"))
        except Exception:
            return None
        return float(value) if isinstance(value, (int, float)) else None

    def time_pos(self):
        return self._property("time-pos")

    def duration(self):
        return self._property("duration")

    def stop(self):
        if self._destroyed:
            return
        try:
            self.mpv.command("stop")
        except Exception:
            pass
        self.path = None
        self.update()
        self.stopped.emit()

    def shutdown(self):
        """Da chiamare alla chiusura: l'ordine (contesto, poi mpv) conta."""
        if self._destroyed:
            return
        self._destroyed = True
        if self._render_context is not None:
            try:
                self._render_context.free()
            except Exception:
                pass
            self._render_context = None
        try:
            self.mpv.terminate()
        except Exception:
            pass

    # Messaggi innocui ma rumorosi: non devono inquinare il log dell'utente.
    _BENIGN = (
        "after creating texture: OpenGL error",
        "av_log callback called with bad parameters",
        "This is a bug in one of FFmpeg libraries",
        "Found duplicated MOOV Atom",
    )

    def _log(self, level, prefix, text):
        text = text.strip()
        if level in ("error", "fatal") and not any(b in text for b in self._BENIGN):
            self.message.emit(f"mpv: {text}")


class AspectBox(QWidget):
    """Contiene il visore mantenendone le proporzioni, centrato.

    Niente layout interno di proposito: un figlio a dimensione fissa alzerebbe
    il minimo del contenitore, che quindi non potrebbe più rimpicciolirsi —
    con lo splitter si otterrebbe un visore che cresce e non torna indietro.
    Qui la geometria del figlio è calcolata a mano e non influenza il genitore.
    """

    MIN_SIDE = 160

    def __init__(self, child, parent=None):
        super().__init__(parent)
        self._child = child
        self._ratio = 16 / 9
        child.setParent(self)
        child.setMinimumSize(1, 1)
        self.setMinimumSize(self.MIN_SIDE, int(self.MIN_SIDE / self._ratio))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._fit()

    def child(self):
        return self._child

    def ratio(self):
        return self._ratio

    def set_ratio(self, width, height):
        """Adatta la proporzione alla sorgente: niente bande nere aggiunte."""
        if not width or not height:
            return
        nuovo = float(width) / float(height)
        if abs(nuovo - self._ratio) > 0.001:
            self._ratio = nuovo
            self._fit()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _fit(self):
        """Il rettangolo più grande con le proporzioni giuste che ci sta dentro."""
        larghezza = min(self.width(), self.height() * self._ratio)
        altezza = larghezza / self._ratio
        x = (self.width() - larghezza) / 2
        y = (self.height() - altezza) / 2
        self._child.setGeometry(int(x), int(y), int(max(1, larghezza)), int(max(1, altezza)))
