"""Aspetto dell'applicazione: tre temi, un solo insieme di ruoli.

Il progetto resta quello di un banco di montaggio: superfici quiete, un accento
che marca ciò che è selezionato o attivo, un colore che compare solo dove si
distrugge qualcosa. Cambia la palette, non il significato dei colori.

Il riquadro del video resta scuro in ogni tema: un'immagine si giudica su un
contorno neutro, non su un pannello chiaro.
"""
import colorsys
import json
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette

PYWAL_COLORS = Path.home() / ".cache" / "wal" / "colors.json"

UI_FAMILIES = ("Adwaita Sans", "Noto Sans", "Cantarell", "DejaVu Sans")
MONO_FAMILIES = ("JetBrainsMono NF", "JetBrains Mono", "Adwaita Mono", "monospace")


@dataclass(frozen=True)
class Palette:
    """I ruoli, non i colori: ogni tema riempie gli stessi nove posti."""
    name: str
    bench: str        # superficie dei pannelli
    well: str         # incavi: campi, log
    raised: str       # controlli in rilievo
    edge: str         # filetti e bordi
    mark: str         # testo principale
    mute: str         # testo secondario
    accent: str       # selezione, testina, azione primaria
    accent_dim: str   # accento premuto o spento
    on_accent: str    # testo sopra l'accento pieno
    danger: str       # solo per ciò che elimina
    viewer: str       # contorno del video: scuro sempre
    is_dark: bool


DARK = Palette(
    name="scuro",
    bench="#1B2124", well="#141A1C", raised="#232B2F", edge="#2E3A3F",
    mark="#D7DEDB", mute="#8A9AA0",
    accent="#E8A33D", accent_dim="#8A6426", on_accent="#141A1C",
    danger="#C2543A", viewer="#101416", is_dark=True,
)

LIGHT = Palette(
    name="chiaro",
    bench="#E8ECEB", well="#F7F9F8", raised="#FFFFFF", edge="#C2CBC9",
    mark="#1B2124", mute="#5E6C69",
    accent="#B4711A", accent_dim="#8A5713", on_accent="#FFFFFF",
    danger="#A33A22", viewer="#101416", is_dark=False,
)


# --------------------------------------------------------------- utilità colore

def _rgb(hex_color):
    c = QColor(hex_color)
    return c.redF(), c.greenF(), c.blueF()


def _hex(r, g, b):
    return QColor.fromRgbF(max(0.0, min(1.0, r)), max(0.0, min(1.0, g)),
                           max(0.0, min(1.0, b))).name()


def _mix(a, b, t):
    """Interpola due colori: t=0 dà `a`, t=1 dà `b`."""
    ar, ag, ab = _rgb(a)
    br, bg, bb = _rgb(b)
    return _hex(ar + (br - ar) * t, ag + (bg - ag) * t, ab + (bb - ab) * t)


def _luminance(hex_color):
    r, g, b = _rgb(hex_color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _hsv(hex_color):
    return colorsys.rgb_to_hsv(*_rgb(hex_color))


# ------------------------------------------------------------------- pywal

def pywal_available() -> bool:
    return PYWAL_COLORS.is_file()


def _pick_accent(colors, sfondo):
    """Il colore più vivido e abbastanza staccato dallo sfondo.

    Gli indici di pywal non hanno semantica — `color1` non è "il rosso", è solo
    il primo colore estratto dall'immagine — quindi si sceglie per saturazione.
    """
    candidati = []
    for c in colors:
        h, s, v = _hsv(c)
        if abs(_luminance(c) - _luminance(sfondo)) < 0.12:
            continue
        candidati.append((s * v, c))
    if not candidati:
        return colors[0] if colors else "#E8A33D"
    return max(candidati)[1]


def _pick_danger(colors, fallback, accent):
    """Un rosso fra i colori del tema, purché non sia l'accento.

    Accento e pericolo devono restare distinguibili: se la tavolozza non offre
    un rosso vero (capita spesso — pywal estrae i colori dall'immagine), meglio
    un rosso fisso che due ruoli dello stesso colore.
    """
    migliore, distanza_migliore = None, 1.0
    for c in colors:
        if c.lower() == accent.lower():
            continue
        h, s, v = _hsv(c)
        if s < 0.3:
            continue
        distanza = min(h, 1.0 - h)          # distanza dalla tinta rossa
        if distanza < distanza_migliore:
            migliore, distanza_migliore = c, distanza
    if migliore is not None and distanza_migliore <= 0.045:
        return migliore
    return fallback


def pywal_palette(path=None):
    """Costruisce la palette dai colori di pywal, o None se non ci sono."""
    path = Path(path) if path else PYWAL_COLORS
    try:
        dati = json.loads(path.read_text(encoding="utf-8"))
        sfondo = dati["special"]["background"]
        testo = dati["special"]["foreground"]
        colori = [dati["colors"][f"color{i}"] for i in range(1, 7)]
    except (OSError, ValueError, KeyError):
        return None

    scuro = _luminance(sfondo) < 0.5
    base = DARK if scuro else LIGHT
    accento = _pick_accent(colori, sfondo)
    return Palette(
        name="pywal",
        bench=_mix(sfondo, testo, 0.06),
        well=sfondo,
        raised=_mix(sfondo, testo, 0.13),
        edge=_mix(sfondo, testo, 0.26),
        mark=testo,
        mute=_mix(sfondo, testo, 0.55),
        accent=accento,
        accent_dim=_mix(accento, sfondo, 0.45),
        on_accent=sfondo if _luminance(accento) > 0.45 else testo,
        danger=_pick_danger(colori, base.danger, accento),
        viewer=_mix(sfondo, "#000000", 0.35) if scuro else DARK.viewer,
        is_dark=scuro,
    )


def available_themes():
    """Nomi dei temi utilizzabili adesso, in ordine di presentazione."""
    nomi = ["scuro", "chiaro"]
    if pywal_available():
        nomi.append("pywal")
    return nomi


def palette_named(name):
    if name == "chiaro":
        return LIGHT
    if name == "pywal":
        return pywal_palette() or DARK
    return DARK


# ------------------------------------------------------------------ caratteri

def _first_available(candidates, fallback_fixed=False):
    disponibili = set(QFontDatabase.families())
    for nome in candidates:
        if nome in disponibili:
            return nome
    return QFontDatabase.systemFont(
        QFontDatabase.FixedFont if fallback_fixed else QFontDatabase.GeneralFont).family()


def ui_font(size=10, weight=QFont.Normal) -> QFont:
    font = QFont(_first_available(UI_FAMILIES), size)
    font.setWeight(weight)
    return font


def mono_font(size=10, weight=QFont.Normal) -> QFont:
    font = QFont(_first_available(MONO_FAMILIES, fallback_fixed=True), size)
    font.setWeight(weight)
    font.setStyleHint(QFont.Monospace)
    return font


# -------------------------------------------------------------- applicazione

_current = DARK


def current() -> Palette:
    """Palette attiva: i widget che si disegnano da soli la leggono qui."""
    return _current


def _qpalette(p: Palette) -> QPalette:
    q = QPalette()
    q.setColor(QPalette.Window, QColor(p.bench))
    q.setColor(QPalette.WindowText, QColor(p.mark))
    q.setColor(QPalette.Base, QColor(p.well))
    q.setColor(QPalette.AlternateBase, QColor(p.raised))
    q.setColor(QPalette.Text, QColor(p.mark))
    q.setColor(QPalette.Button, QColor(p.raised))
    q.setColor(QPalette.ButtonText, QColor(p.mark))
    q.setColor(QPalette.Highlight, QColor(p.accent))
    q.setColor(QPalette.HighlightedText, QColor(p.on_accent))
    q.setColor(QPalette.ToolTipBase, QColor(p.raised))
    q.setColor(QPalette.ToolTipText, QColor(p.mark))
    q.setColor(QPalette.PlaceholderText, QColor(p.mute))
    for ruolo in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        q.setColor(QPalette.Disabled, ruolo, QColor(p.mute))
    return q


def stylesheet(p: Palette = None) -> str:
    p = p or _current
    hover_accent = _mix(p.accent, p.mark, 0.25)
    return f"""
QWidget {{ background: {p.bench}; color: {p.mark}; }}

QGroupBox {{
    border: 1px solid {p.edge};
    border-radius: 4px;
    margin-top: 16px;
    padding: 10px 10px 8px 10px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: {p.mute};
}}

QLineEdit, QTextEdit, QListWidget, QAbstractSpinBox, QComboBox {{
    background: {p.well};
    border: 1px solid {p.edge};
    border-radius: 4px;
    padding: 5px 7px;
    selection-background-color: {p.accent};
    selection-color: {p.on_accent};
}}
QLineEdit:focus, QTextEdit:focus, QListWidget:focus,
QAbstractSpinBox:focus, QComboBox:focus {{ border-color: {p.accent}; }}
QLineEdit:read-only {{ color: {p.mute}; }}

QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{
    background: {p.raised};
    border: 1px solid {p.edge};
    selection-background-color: {p.accent};
    selection-color: {p.on_accent};
}}

QPushButton {{
    background: {p.raised};
    border: 1px solid {p.edge};
    border-radius: 4px;
    padding: 6px 12px;
}}
QPushButton:hover {{ border-color: {p.mute}; }}
QPushButton:pressed {{ background: {p.well}; }}
QPushButton:disabled {{ background: {p.bench}; color: {p.mute}; border-color: {p.edge}; }}

QPushButton#primary {{
    background: {p.accent};
    color: {p.on_accent};
    border: 1px solid {p.accent};
    font-weight: 600;
}}
QPushButton#primary:hover {{ background: {hover_accent}; border-color: {hover_accent}; }}
QPushButton#primary:pressed {{ background: {p.accent_dim}; }}

QPushButton#accent {{ color: {p.accent}; border-color: {p.accent_dim}; }}
QPushButton#accent:hover {{ border-color: {p.accent}; background: {p.raised}; }}

QPushButton#danger {{ color: {p.danger}; border-color: {p.danger}; }}
QPushButton#danger:hover {{ background: {p.danger}; color: {p.on_accent}; }}

QTabWidget::pane {{ border: none; border-top: 1px solid {p.edge}; top: -1px; }}
QTabBar::tab {{
    background: transparent;
    color: {p.mute};
    padding: 7px 16px;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:hover {{ color: {p.mark}; }}
QTabBar::tab:selected {{ color: {p.mark}; border-bottom: 2px solid {p.accent}; }}

QCheckBox {{ spacing: 7px; }}
QCheckBox::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {p.edge};
    border-radius: 3px;
    background: {p.well};
}}
QCheckBox::indicator:hover {{ border-color: {p.mute}; }}
QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent}; }}

QProgressBar {{
    background: {p.well};
    border: 1px solid {p.edge};
    border-radius: 3px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {p.accent}; border-radius: 2px; }}

QScrollBar:vertical {{ background: {p.well}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {p.edge}; border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {p.mute}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: {p.well}; height: 10px; }}
QScrollBar::handle:horizontal {{ background: {p.edge}; border-radius: 5px; min-width: 24px; }}

QStatusBar {{ color: {p.mute}; border-top: 1px solid {p.edge}; }}
QStatusBar::item {{ border: none; }}
QToolTip {{
    background: {p.raised};
    color: {p.mark};
    border: 1px solid {p.edge};
    padding: 4px 6px;
}}
QLabel#sectionLabel {{ color: {p.mute}; }}
QFrame#viewer {{ background: {p.viewer}; border: 1px solid {p.edge}; }}
"""


def apply(app, name="scuro"):
    """Applica un tema all'applicazione. Si può chiamare a caldo."""
    global _current
    _current = palette_named(name)
    app.setStyle("Fusion")
    app.setPalette(_qpalette(_current))
    app.setFont(ui_font())
    app.setStyleSheet(stylesheet(_current))
    return _current
