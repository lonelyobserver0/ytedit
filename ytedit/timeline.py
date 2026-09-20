"""Barra temporale: scorrimento del video e selezione dell'intervallo."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFontMetrics, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import theme

TRACK_HEIGHT = 26
HANDLE_WIDTH = 9
GRAB_TOLERANCE = 10          # px entro cui si "afferra" una maniglia
MARGIN = HANDLE_WIDTH        # spazio ai lati per non tagliare le maniglie


def format_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours, rest = divmod(int(seconds), 3600)
    minutes, secs = divmod(rest, 60)
    frazione = int((seconds - int(seconds)) * 10)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}.{frazione}"
    return f"{minutes:02d}:{secs:02d}.{frazione}"


class Timeline(QWidget):
    """Testina trascinabile più maniglie IN/OUT sulla stessa barra."""

    seek_requested = Signal(float)      # l'utente trascina la testina
    selection_changed = Signal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(TRACK_HEIGHT + 40)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

        self._duration = 0.0
        self._position = 0.0
        self._in = 0.0
        self._out = 0.0
        self._dragging = None            # "in" | "out" | "position"

    # ------------------------------------------------------------- stato

    def duration(self):
        return self._duration

    def set_duration(self, seconds):
        self._duration = max(0.0, float(seconds or 0.0))
        self._out = self._out or self._duration
        self._clamp()
        self.update()

    def set_position(self, seconds):
        if self._dragging == "position":
            return                        # non contrastare il trascinamento
        self._position = max(0.0, min(float(seconds or 0.0), self._duration or 0.0))
        self.update()

    def selection(self):
        return self._in, self._out

    def set_selection(self, start, end):
        self._in, self._out = float(start or 0.0), float(end or 0.0)
        self._clamp()
        self.update()

    def _clamp(self):
        limite = self._duration or max(self._out, self._in, 1.0)
        self._in = max(0.0, min(self._in, limite))
        self._out = max(self._in, min(self._out, limite))
        self._position = max(0.0, min(self._position, limite))

    # ---------------------------------------------------------- geometria

    def _track_rect(self) -> QRectF:
        return QRectF(MARGIN, 20, max(1, self.width() - 2 * MARGIN), TRACK_HEIGHT)

    def _tick_step(self) -> float:
        """Passo delle perforazioni: un valore leggibile, non una griglia fitta."""
        if not self._duration:
            return 0.0
        larghezza = self._track_rect().width()
        for passo in (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600):
            if larghezza * passo / self._duration >= 46:
                return passo
        return self._duration / 4

    def _x_for(self, seconds) -> float:
        track = self._track_rect()
        if not self._duration:
            return track.left()
        return track.left() + track.width() * (seconds / self._duration)

    def _time_for(self, x) -> float:
        track = self._track_rect()
        if not self._duration or track.width() <= 0:
            return 0.0
        ratio = (x - track.left()) / track.width()
        return max(0.0, min(1.0, ratio)) * self._duration

    def _handle_at(self, x):
        if not self._duration:
            return None
        if abs(x - self._x_for(self._in)) <= GRAB_TOLERANCE:
            return "in"
        if abs(x - self._x_for(self._out)) <= GRAB_TOLERANCE:
            return "out"
        return None

    # ------------------------------------------------------------- mouse

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or not self._duration:
            return
        x = event.position().x()
        self._dragging = self._handle_at(x) or "position"
        self._apply_drag(x)

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._apply_drag(event.position().x())
            return
        sopra = self._handle_at(event.position().x())
        self.setCursor(Qt.SizeHorCursor if sopra else Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        self._dragging = None

    def _apply_drag(self, x):
        t = self._time_for(x)
        if self._dragging == "in":
            self._in = min(t, self._out)
            self.selection_changed.emit(self._in, self._out)
        elif self._dragging == "out":
            self._out = max(t, self._in)
            self.selection_changed.emit(self._in, self._out)
        else:
            self._position = t
            self.seek_requested.emit(t)
        self.update()

    # ------------------------------------------------------------ disegno

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        track = self._track_rect()

        tavolozza = theme.current()
        bordo = QColor(tavolozza.edge)
        ambra = QColor(tavolozza.accent)
        segno = QColor(tavolozza.mark)
        spento = QColor(tavolozza.mute)

        # La pellicola: incavo scuro con filetto.
        painter.setPen(QPen(bordo, 1))
        painter.setBrush(QBrush(QColor(tavolozza.well)))
        painter.drawRoundedRect(track.adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)

        if self._duration:
            passo = self._tick_step()
            if passo:
                painter.setPen(QPen(bordo, 1))
                t = passo
                while t < self._duration:
                    x = self._x_for(t)
                    painter.drawLine(int(x), int(track.top() + 4),
                                     int(x), int(track.bottom() - 4))
                    t += passo

            inizio, fine = self._x_for(self._in), self._x_for(self._out)
            # Il nastro: la parte selezionata, in ambra.
            nastro = QRectF(inizio, track.top() + 1, max(1.0, fine - inizio), track.height() - 2)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(ambra.red(), ambra.green(), ambra.blue(), 70)))
            painter.drawRect(nastro)
            painter.setPen(QPen(ambra, 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(nastro.adjusted(0.5, 0.5, -0.5, -0.5))

            # Maniglie a staffa: si vede da che lato si afferra.
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(ambra))
            for x, verso in ((inizio, 1), (fine, -1)):
                gambo = QRectF(x - 1.5, track.top() - 3, 3, track.height() + 6)
                painter.drawRect(gambo)
                for y in (track.top() - 3, track.bottom() - 1):
                    painter.drawRect(QRectF(x - 1.5, y, 7 * verso, 4))

            # Testina di riproduzione: l'unica cosa bianca sulla barra.
            px = self._x_for(self._position)
            painter.setPen(QPen(segno, 1.5))
            painter.drawLine(QPointF(px, track.top() - 6), QPointF(px, track.bottom() + 6))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(segno))
            painter.drawPolygon(QPolygonF([
                QPointF(px - 5, track.top() - 13),
                QPointF(px + 5, track.top() - 13),
                QPointF(px, track.top() - 5),
            ]))
        else:
            painter.setPen(QPen(spento))
            painter.setFont(theme.ui_font(9))
            painter.drawText(track, Qt.AlignCenter, "Nessuna sorgente caricata")

        # Timecode in monospaziato: cifre incolonnate, si confrontano a colpo d'occhio.
        painter.setFont(theme.mono_font(9))
        metriche = QFontMetrics(painter.font())
        base = int(track.bottom() + metriche.height() + 3)
        painter.setPen(QPen(segno))
        painter.drawText(int(track.left()), base, format_time(self._position))
        painter.setPen(QPen(ambra))
        durata_sel = max(0.0, self._out - self._in)
        etichetta = f"{format_time(self._in)}  {format_time(self._out)}   {format_time(durata_sel)}"
        painter.drawText(int(track.center().x() - metriche.horizontalAdvance(etichetta) / 2),
                         base, etichetta)
        painter.setPen(QPen(spento))
        totale = format_time(self._duration)
        painter.drawText(int(track.right() - metriche.horizontalAdvance(totale)), base, totale)
