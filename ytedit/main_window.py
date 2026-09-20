"""Finestra principale di ytEdit."""
from __future__ import annotations

import functools
import inspect
import shlex
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import Qt, QSettings, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QSplitter, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox, QProgressBar,
    QTextEdit, QFileDialog, QListWidget, QListWidgetItem, QGroupBox,
    QTabWidget, QDoubleSpinBox, QMessageBox, QSizePolicy, QFrame,
)

from .downloader import (
    KEEP_ORIGINAL, AnalyzeWorker, YTDLPWorker, analyze_command, audio_format_value,
    build_command, build_format,
)
from .ffmpeg import (
    FFmpegError, burn_subtitles_cmd, concat_copy_cmd, concat_encode_cmd,
    cut_cmd, extract_audio_cmd, format_timestamp, media_info, mux_subtitles_cmd,
    parse_timestamp, remove_section_cmd, replace_audio_cmd, transform_cmd,
    write_concat_list,
)
from .player import MPVPlayer, is_url, ytdl_path
from .timeline import Timeline
from . import theme
from . import video_widget
from .video_widget import AspectBox
from .workers import ProcessWorker

QUALITIES = ["Best disponibile", "1080p", "720p", "480p", "360p"]
CONTAINERS = ["MP4", "MKV", "WEBM"]
AUDIO_FORMATS = [KEEP_ORIGINAL, "opus", "m4a", "mp3", "flac", "wav"]
STATUS_ICONS = {"in attesa": "⏳", "in corso": "▶", "completato": "✔",
                "errore": "✖", "interrotto": "⏹"}


def safe_slot(method):
    """Uno slot non deve mai propagare eccezioni: in PySide6 abbattono l'app.

    L'errore finisce nel log dell'applicazione invece che in un terminale che
    nessuno sta guardando.
    """
    # Qt passa gli argomenti del segnale (es. clicked(bool), textChanged(str)):
    # li tronchiamo alla firma del metodo, come farebbe PySide6 senza wrapper.
    parameters = list(inspect.signature(method).parameters.values())
    accepts_varargs = any(p.kind is p.VAR_POSITIONAL for p in parameters)
    max_positional = sum(
        1 for p in parameters
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ) - 1  # esclude self

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        if not accepts_varargs:
            args = args[:max_positional]
        try:
            return method(self, *args, **kwargs)
        except Exception:
            details = traceback.format_exc()
            if getattr(self, "log", None) is None:  # eccezione durante la costruzione
                print(details, file=sys.stderr)
                return None
            self.log_line(f"✖ Errore interno in {method.__name__}:\n{details}")
            self.statusBar().showMessage(f"Errore interno in {method.__name__}")
            return None
    return wrapper


@dataclass
class Job:
    url: str
    opts: dict = field(default_factory=dict)
    status: str = "in attesa"
    title: str = ""

    def label(self) -> str:
        return f"{STATUS_ICONS.get(self.status, '•')} {self.title or self.url}"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ytEdit — yt-dlp + FFmpeg")
        self.resize(1200, 860)
        self.settings = QSettings("ytEdit", "ytEdit")

        self.download_worker = None
        self.analyze_worker = None
        self.process_worker = None
        self.video = None          # widget video integrato, se disponibile
        if video_widget.is_available():
            self.video = video_widget.VideoWidget(ytdl_path=ytdl_path())
            self.player = self.video
        else:
            self.player = MPVPlayer(self)
        self.player.message.connect(self.log_line)

        self.jobs: list[Job] = []
        self.active_job = None
        self.queue_active = False
        self.current_file = None
        self._pending_output = None
        self._pending_op = ""
        self._temp_files: list[Path] = []
        self._remote_duration = 0.0
        self._analyzed_url = ""
        self._ipc_failures = 0

        self._build()
        self._restore_settings()
        self._update_preview()

        self.position_timer = QTimer(self)
        self.position_timer.setInterval(500)
        self.position_timer.timeout.connect(self._update_position)

    # ------------------------------------------------------------------ UI

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 12, 14, 10)
        layout.setSpacing(10)

        urlrow = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setPlaceholderText("URL YouTube / Vimeo / sito supportato da yt-dlp…")
        self.url.returnPressed.connect(self.analyze)
        analyze = QPushButton("Analizza")
        analyze.setObjectName("accent")
        analyze.clicked.connect(self.analyze)
        urlrow.addWidget(self.url, 1)
        urlrow.addWidget(analyze)
        layout.addLayout(urlrow)

        self.url_info = QLabel("")
        self.url_info.setWordWrap(True)
        self.url_info.setObjectName("sectionLabel")
        layout.addWidget(self.url_info)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._download_tab(), "Download")
        self.tabs.addTab(self._edit_tab(), "Editor")
        self.tabs.addTab(self._tools_tab(), "Strumenti")
        self.tabs.addTab(self._advanced_tab(), "Avanzato")
        layout.addWidget(self.tabs, 1)

        self.progress = QProgressBar()
        layout.addWidget(self.progress)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(150)
        self.log.setFont(theme.mono_font(9))
        etichetta_log = QLabel("Log")
        etichetta_log.setObjectName("sectionLabel")
        layout.addWidget(etichetta_log)
        layout.addWidget(self.log)

        self.statusBar().showMessage("Pronto")

    @staticmethod
    def _section_label(testo):
        etichetta = QLabel(testo)
        etichetta.setObjectName("sectionLabel")
        return etichetta

    def _download_tab(self):
        w = QWidget()
        g = QGridLayout(w)

        g.addWidget(QLabel("Qualità"), 0, 0)
        self.quality = QComboBox()
        self.quality.addItems(QUALITIES)
        g.addWidget(self.quality, 0, 1)

        g.addWidget(QLabel("Contenitore"), 1, 0)
        self.container = QComboBox()
        self.container.addItems(CONTAINERS)
        g.addWidget(self.container, 1, 1)

        self.audio_only = QCheckBox("Solo audio")
        self.audio_format = QComboBox()
        self.audio_format.addItems(AUDIO_FORMATS)
        self.audio_format.setToolTip(
            "«originale» tiene il flusso audio così com'è, senza ricodificarlo:\n"
            "è la qualità migliore possibile e anche il file più piccolo.\n"
            "Gli altri formati ricodificano, quindi perdono qualcosa."
        )
        self.audio_only.toggled.connect(self._sync_download_controls)
        g.addWidget(self.audio_only, 2, 0)
        g.addWidget(self.audio_format, 2, 1)

        self.subs = QCheckBox("Scarica sottotitoli")
        self.sub_langs = QLineEdit("all")
        self.sub_langs.setToolTip("Lingue separate da virgola, es. it,en — oppure 'all'")
        self.subs.toggled.connect(self._sync_download_controls)
        g.addWidget(self.subs, 3, 0)
        g.addWidget(self.sub_langs, 3, 1)

        self.section = QCheckBox("Solo selezione IN–OUT")
        self.section.setToolTip(
            "Scarica soltanto l'intervallo scelto nell'editor, senza prendere\n"
            "tutto il video (yt-dlp --download-sections)."
        )
        g.addWidget(self.section, 2, 2)

        self.playlist = QCheckBox("Intera playlist")
        self.playlist.setToolTip(
            "Spento: da un URL con '&list=' scarica solo il video indicato.\n"
            "Acceso: scarica tutta la playlist in una sottocartella dedicata."
        )
        g.addWidget(self.playlist, 3, 2)

        self.outdir = QLineEdit(str(Path.home() / "Downloads"))
        browse = QPushButton("Sfoglia…")
        browse.clicked.connect(self.choose_dir)
        g.addWidget(QLabel("Destinazione"), 4, 0)
        g.addWidget(self.outdir, 4, 1)
        g.addWidget(browse, 4, 2)

        row = QHBoxLayout()
        enqueue = QPushButton("+ Aggiungi alla coda")
        enqueue.clicked.connect(lambda: self.enqueue(start=False))
        download = QPushButton("Scarica")
        download.setObjectName("primary")
        download.clicked.connect(lambda: self.enqueue(start=True))
        stop = QPushButton("Interrompi")
        stop.clicked.connect(self.stop_download)
        row.addWidget(enqueue)
        row.addWidget(download)
        row.addWidget(stop)
        g.addLayout(row, 5, 0, 1, 3)

        g.addWidget(self._section_label("Coda"), 6, 0)
        self.queue = QListWidget()
        g.addWidget(self.queue, 7, 0, 1, 3)

        queue_row = QHBoxLayout()
        remove = QPushButton("Rimuovi selezionato")
        remove.clicked.connect(self.remove_job)
        clear = QPushButton("Svuota completati")
        clear.clicked.connect(self.clear_finished_jobs)
        queue_row.addWidget(remove)
        queue_row.addWidget(clear)
        queue_row.addStretch(1)
        g.addLayout(queue_row, 8, 0, 1, 3)

        for widget in (self.quality, self.container, self.audio_format):
            widget.currentTextChanged.connect(self._update_preview)
        for widget in (self.audio_only, self.subs, self.playlist, self.section):
            widget.toggled.connect(self._update_preview)
        for widget in (self.outdir, self.sub_langs):
            widget.textChanged.connect(self._update_preview)
        return w

    def _edit_tab(self):
        """Due colonne: a sinistra si decide, a destra si guarda.

        Lo splitter lascia all'utente la proporzione fra le due: chi monta a
        occhio allarga il visore, chi lavora sui parametri lo stringe.
        """
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        file_row = QHBoxLayout()
        self.edit_file = QLineEdit()
        self.edit_file.textChanged.connect(self._on_file_changed)
        browse = QPushButton("Apri…")
        browse.clicked.connect(self.choose_edit_file)
        file_row.addWidget(self.edit_file, 1)
        file_row.addWidget(browse)
        root.addLayout(file_row)

        self.editor_splitter = QSplitter(Qt.Horizontal)
        self.editor_splitter.setChildrenCollapsible(False)
        self.editor_splitter.addWidget(self._edit_controls())
        self.editor_splitter.addWidget(self._edit_viewer())
        self.editor_splitter.setStretchFactor(0, 0)
        self.editor_splitter.setStretchFactor(1, 1)
        self.editor_splitter.setSizes([420, 620])
        self.editor_splitter.splitterMoved.connect(self._save_splitter)
        root.addWidget(self.editor_splitter, 1)
        return w

    def _edit_controls(self):
        """Colonna sinistra: taglio, trasformazioni, audio."""
        pannello = QWidget()
        layout = QVBoxLayout(pannello)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        cutbox = QGroupBox("Taglio")
        cg = QGridLayout(cutbox)
        self.in_time = QLineEdit("00:00:00")
        self.out_time = QLineEdit("00:00:10")
        for campo in (self.in_time, self.out_time):
            campo.setFont(theme.mono_font(10))
        self.precise = QCheckBox("Taglio preciso (ricodifica)")
        self.precise.setChecked(True)
        cut = QPushButton("✂ Tieni solo la selezione")
        cut.clicked.connect(self.cut)
        remove = QPushButton("✀ Rimuovi la selezione")
        remove.setObjectName("danger")
        remove.setToolTip("Elimina l'intervallo IN–OUT e ricuce le parti rimanenti.")
        remove.clicked.connect(self.remove_section)
        cg.addWidget(QLabel("IN"), 0, 0)
        cg.addWidget(self.in_time, 0, 1)
        cg.addWidget(QLabel("OUT"), 1, 0)
        cg.addWidget(self.out_time, 1, 1)
        cg.addWidget(self.precise, 2, 0, 1, 2)
        cg.addWidget(cut, 3, 0, 1, 2)
        cg.addWidget(remove, 4, 0, 1, 2)
        layout.addWidget(cutbox)

        trans = QGroupBox("Video / Audio")
        tg = QGridLayout(trans)
        self.scale_width = QLineEdit()
        self.scale_width.setPlaceholderText("es. 1280 o -1")
        self.scale_height = QLineEdit()
        self.scale_height.setPlaceholderText("es. 720 o -1")
        self.rotate = QComboBox()
        self.rotate.addItems(["none", "90", "180", "270"])
        self.volume = QDoubleSpinBox()
        self.volume.setRange(0, 5)
        self.volume.setValue(1.0)
        self.volume.setSingleStep(.1)
        self.fadein = QLineEdit()
        self.fadeout = QLineEdit()
        for r, (name, widget) in enumerate([
                ("Larghezza", self.scale_width), ("Altezza", self.scale_height),
                ("Rotazione", self.rotate), ("Volume", self.volume),
                ("Fade in (s)", self.fadein), ("Fade out (s)", self.fadeout)]):
            tg.addWidget(QLabel(name), r, 0)
            tg.addWidget(widget, r, 1)
        transform = QPushButton("Applica trasformazioni")
        transform.clicked.connect(self.transform)
        tg.addWidget(transform, 6, 0, 1, 2)
        layout.addWidget(trans)

        audio = QGroupBox("Audio")
        ag = QGridLayout(audio)
        extract = QPushButton("Estrai audio")
        extract.clicked.connect(self.extract_audio)
        replace = QPushButton("Sostituisci traccia audio")
        replace.clicked.connect(self.replace_audio)
        ag.addWidget(extract, 0, 0)
        ag.addWidget(replace, 0, 1)
        layout.addWidget(audio)
        layout.addStretch(1)

        for widget in (self.in_time, self.out_time, self.scale_width, self.scale_height,
                       self.fadein, self.fadeout):
            widget.textChanged.connect(self._update_preview)
        self.in_time.textChanged.connect(self._sync_timeline_selection)
        self.out_time.textChanged.connect(self._sync_timeline_selection)
        self.rotate.currentTextChanged.connect(self._update_preview)
        self.volume.valueChanged.connect(self._update_preview)
        self.precise.toggled.connect(self._update_preview)
        return pannello

    def _edit_viewer(self):
        """Colonna destra: il video, la sua barra e i comandi che lo guidano."""
        pannello = QWidget()
        layout = QVBoxLayout(pannello)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        if self.video is not None:
            self.video.setObjectName("viewer")
            self.video_frame = self.video
        else:
            # Ripiego: mpv come processo esterno agganciato a questa finestra.
            self.video_frame = QFrame()
            self.video_frame.setObjectName("viewer")
            self.video_frame.setAttribute(Qt.WA_NativeWindow, True)
        self.viewer_box = AspectBox(self.video_frame)
        layout.addWidget(self.viewer_box, 1)

        self.timeline = Timeline()
        self.timeline.seek_requested.connect(self._timeline_seek)
        self.timeline.selection_changed.connect(self._timeline_selection)
        layout.addWidget(self.timeline)

        self.position_label = QLabel("--:--:--")
        self.position_label.setFont(theme.mono_font(10, QFont.Medium))
        play = QPushButton("▶ Riproduci")
        play.clicked.connect(self.play_file)
        pause = QPushButton("⏯ Pausa")
        pause.clicked.connect(self.player.toggle_pause)
        stop = QPushButton("⏹ Stop")
        stop.clicked.connect(self.stop_player)
        back = QPushButton("⏪ −5s")
        back.clicked.connect(lambda: self._skip(-5))
        forward = QPushButton("+5s ⏩")
        forward.clicked.connect(lambda: self._skip(5))
        trasporto = QHBoxLayout()
        for widget in (play, pause, stop, back, forward):
            trasporto.addWidget(widget)
        trasporto.addStretch(1)
        trasporto.addWidget(self.position_label)
        layout.addLayout(trasporto)

        set_in = QPushButton("IN = posizione")
        set_in.clicked.connect(lambda: self._set_time_from_player(self.in_time))
        set_out = QPushButton("OUT = posizione")
        set_out.clicked.connect(lambda: self._set_time_from_player(self.out_time))
        grab = QPushButton("⬇ Scarica IN–OUT")
        grab.setObjectName("primary")
        grab.setToolTip("Scarica dall'URL solo l'intervallo selezionato.")
        grab.clicked.connect(self.download_section)
        marcatura = QHBoxLayout()
        for widget in (set_in, set_out):
            marcatura.addWidget(widget)
        marcatura.addStretch(1)
        marcatura.addWidget(grab)
        layout.addLayout(marcatura)

        self.media_info_label = QLabel("Nessun file caricato.")
        self.media_info_label.setObjectName("sectionLabel")
        layout.addWidget(self.media_info_label)
        return pannello

    def _tools_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        concat = QGroupBox("Unisci file")
        cg = QGridLayout(concat)
        self.concat_list = QListWidget()
        cg.addWidget(self.concat_list, 0, 0, 6, 1)
        buttons = [
            ("Aggiungi…", self.add_concat_files),
            ("Rimuovi", self.remove_concat_file),
            ("▲ Su", lambda: self.move_concat_file(-1)),
            ("▼ Giù", lambda: self.move_concat_file(1)),
            ("Svuota", self.concat_list.clear),
        ]
        for row, (text, slot) in enumerate(buttons):
            button = QPushButton(text)
            button.clicked.connect(slot)
            cg.addWidget(button, row, 1)
        self.concat_reencode = QCheckBox("Ricodifica (file con codec diversi)")
        cg.addWidget(self.concat_reencode, 6, 0)
        run_concat = QPushButton("Unisci")
        run_concat.clicked.connect(self.concat)
        cg.addWidget(run_concat, 6, 1)
        layout.addWidget(concat)

        subs = QGroupBox("Sottotitoli (sul file dell'editor)")
        sg = QGridLayout(subs)
        self.sub_file = QLineEdit()
        self.sub_file.setPlaceholderText("File .srt / .ass / .vtt…")
        pick = QPushButton("Sfoglia…")
        pick.clicked.connect(self.choose_sub_file)
        sg.addWidget(QLabel("Sottotitoli"), 0, 0)
        sg.addWidget(self.sub_file, 0, 1)
        sg.addWidget(pick, 0, 2)
        burn = QPushButton("Masterizza nel video (burn-in)")
        burn.clicked.connect(self.burn_subtitles)
        mux = QPushButton("Incorpora come traccia")
        mux.clicked.connect(self.mux_subtitles)
        sg.addWidget(burn, 1, 1)
        sg.addWidget(mux, 1, 2)
        layout.addWidget(subs)

        layout.addStretch(1)
        return w

    def _advanced_tab(self):
        w = QWidget()
        g = QVBoxLayout(w)
        self.extra = QTextEdit()
        self.extra.setFont(theme.mono_font(9))
        self.extra.setPlaceholderText("Argomenti extra yt-dlp, uno per riga (es. --cookies-from-browser firefox)")
        self.extra.setMaximumHeight(120)
        self.extra.textChanged.connect(self._update_preview)
        aspetto = QHBoxLayout()
        aspetto.addWidget(self._section_label("Aspetto"))
        self.theme_box = QComboBox()
        self.theme_box.addItems(theme.available_themes())
        if "pywal" not in theme.available_themes():
            self.theme_box.setToolTip(
                "Il tema pywal compare quando esiste ~/.cache/wal/colors.json")
        self.theme_box.currentTextChanged.connect(self.change_theme)
        aspetto.addWidget(self.theme_box)
        aspetto.addStretch(1)
        g.addLayout(aspetto)

        g.addWidget(self._section_label("Argomenti yt-dlp"))
        g.addWidget(self.extra)

        self.cmd_preview = QTextEdit()
        self.cmd_preview.setReadOnly(True)
        self.cmd_preview.setLineWrapMode(QTextEdit.NoWrap)
        self.cmd_preview.setFont(theme.mono_font(9))
        g.addWidget(self._section_label("Anteprima comandi (aggiornata in tempo reale)"))
        g.addWidget(self.cmd_preview, 1)

        row = QHBoxLayout()
        stop_ff = QPushButton("Interrompi operazione FFmpeg")
        stop_ff.clicked.connect(self.stop_ffmpeg)
        row.addWidget(stop_ff)
        row.addStretch(1)
        g.addLayout(row)
        return w

    # ------------------------------------------------------- impostazioni

    def _restore_settings(self):
        s = self.settings
        geometry = s.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)
        self.outdir.setText(s.value("download/outdir", str(Path.home() / "Downloads")))
        self.quality.setCurrentText(s.value("download/quality", QUALITIES[0]))
        self.container.setCurrentText(s.value("download/container", CONTAINERS[0]))
        self.audio_format.setCurrentText(s.value("download/audio_format", KEEP_ORIGINAL))
        self.sub_langs.setText(s.value("download/sub_langs", "all"))
        self.audio_only.setChecked(s.value("download/audio_only", False, type=bool))
        self.subs.setChecked(s.value("download/subs", False, type=bool))
        self.playlist.setChecked(s.value("download/playlist", False, type=bool))
        self.precise.setChecked(s.value("edit/precise", True, type=bool))
        self.extra.setPlainText(s.value("advanced/extra", ""))
        stato = s.value("edit/splitter")
        if stato:
            self.editor_splitter.restoreState(stato)
        salvato = s.value("ui/theme", "scuro")
        if salvato in theme.available_themes():
            self.theme_box.setCurrentText(salvato)
        self._sync_download_controls()

    def _save_settings(self):
        s = self.settings
        s.setValue("window/geometry", self.saveGeometry())
        s.setValue("download/outdir", self.outdir.text())
        s.setValue("download/quality", self.quality.currentText())
        s.setValue("download/container", self.container.currentText())
        s.setValue("download/audio_format", self.audio_format.currentText())
        s.setValue("download/sub_langs", self.sub_langs.text())
        s.setValue("download/audio_only", self.audio_only.isChecked())
        s.setValue("download/subs", self.subs.isChecked())
        s.setValue("download/playlist", self.playlist.isChecked())
        s.setValue("edit/precise", self.precise.isChecked())
        s.setValue("advanced/extra", self.extra.toPlainText())
        s.setValue("edit/splitter", self.editor_splitter.saveState())
        s.sync()

    def _sync_download_controls(self):
        audio = self.audio_only.isChecked()
        self.audio_format.setEnabled(audio)
        self.container.setEnabled(not audio)
        self.quality.setEnabled(not audio)
        self.sub_langs.setEnabled(self.subs.isChecked())

    @safe_slot
    def _save_splitter(self, *_):
        self.settings.setValue("edit/splitter", self.editor_splitter.saveState())

    @safe_slot
    def change_theme(self, nome):
        """Applica il tema subito: nessun riavvio, nessuna finestra da riaprire."""
        app = QApplication.instance()
        if app is None:
            return
        tavolozza = theme.apply(app, nome)
        self.settings.setValue("ui/theme", nome)
        self.timeline.update()
        if self.video is not None:
            self.video.update()
        self.statusBar().showMessage(f"Tema: {tavolozza.name}")

    # ------------------------------------------------------------- utilità

    def log_line(self, text):
        self.log.append(text)

    def extra_args(self) -> list[str]:
        args = []
        for line in self.extra.toPlainText().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                try:
                    args += shlex.split(line)
                except ValueError as exc:
                    self.log_line(f"Argomenti extra ignorati ({line}): {exc}")
        return args

    def download_options(self) -> dict:
        return {
            "output_dir": self.outdir.text(),
            "fmt": build_format(self.quality.currentText()),
            "audio_only": self.audio_only.isChecked(),
            "subtitles": self.subs.isChecked(),
            "container": self.container.currentText(),
            "sub_langs": self.sub_langs.text(),
            "audio_format": audio_format_value(self.audio_format.currentText()),
            "extra_args": self.extra_args(),
            "playlist": self.playlist.isChecked(),
            "section": self.selected_section(),
        }

    def selected_section(self):
        """(IN, OUT) se la casella è attiva e i tempi sono validi, altrimenti None."""
        if not self.section.isChecked():
            return None
        try:
            start = parse_timestamp(self.in_time.text())
            end = parse_timestamp(self.out_time.text())
        except FFmpegError:
            return None
        if end <= start:
            return None
        return (format_timestamp(start), format_timestamp(end))

    def choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Cartella destinazione", self.outdir.text())
        if d:
            self.outdir.setText(d)

    def choose_edit_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Apri media", str(Path.home()))
        if f:
            self.edit_file.setText(f)

    def choose_sub_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Seleziona sottotitoli", str(Path.home()),
                                           "Sottotitoli (*.srt *.ass *.ssa *.vtt);;Tutti i file (*)")
        if f:
            self.sub_file.setText(f)

    @safe_slot
    def _on_file_changed(self, path):
        path = path.strip()
        self.current_file = path or None
        if is_url(path):
            details = ["sorgente remota (streaming)"]
            if self._remote_duration:
                details.append(f"durata {format_timestamp(self._remote_duration)}")
                self.timeline.set_duration(self._remote_duration)
                self.in_time.setText("00:00:00")
                self.out_time.setText(format_timestamp(self._remote_duration))
            details.append("scarica il segmento per usare gli strumenti FFmpeg")
            self.media_info_label.setText(" · ".join(details))
            self._update_preview()
            return
        if path and Path(path).exists():
            info = media_info(path)
            details = []
            if info.duration:
                details.append(f"durata {format_timestamp(info.duration)}")
            if info.width and info.height:
                details.append(f"{info.width}×{info.height}")
            details.append("video" if info.has_video else "nessun video")
            details.append("audio" if info.has_audio else "nessun audio")
            self.media_info_label.setText(" · ".join(details))
            self.viewer_box.set_ratio(info.width, info.height)
            if info.duration:
                self.timeline.set_duration(info.duration)
                self.out_time.setText(format_timestamp(info.duration))
                self.in_time.setText("00:00:00")
        else:
            self.media_info_label.setText("Nessun file caricato.")
        self._update_preview()

    def source_file(self):
        """Path del file locale in editor, o None (con avviso) se non utilizzabile."""
        path = self.edit_file.text().strip()
        if not path:
            QMessageBox.warning(self, "ytEdit", "Seleziona prima un file nell'editor.")
            return None
        if is_url(path):
            QMessageBox.information(
                self, "ytEdit",
                "La sorgente è un URL in streaming: gli strumenti FFmpeg lavorano su "
                "file locali.\nUsa «⬇ Scarica IN–OUT» per ottenere il segmento, poi "
                "ripeti l'operazione."
            )
            return None
        if not Path(path).exists():
            QMessageBox.warning(self, "ytEdit", f"File non trovato:\n{path}")
            return None
        return path

    def output_path(self, suffix, ext=None):
        """Mantiene l'estensione della sorgente salvo richiesta diversa."""
        src = Path(self.edit_file.text().strip())
        suffix_ext = ext or (src.suffix if src.suffix else ".mp4")
        candidate = src.with_name(src.stem + suffix + suffix_ext)
        index = 1
        while candidate.exists():
            candidate = src.with_name(f"{src.stem}{suffix}_{index}{suffix_ext}")
            index += 1
        return str(candidate)

    @safe_slot
    def _sync_timeline_selection(self):
        """Campi IN/OUT → timeline (l'altro verso passa da _timeline_selection)."""
        try:
            start = parse_timestamp(self.in_time.text())
            end = parse_timestamp(self.out_time.text())
        except FFmpegError:
            return
        self.timeline.set_selection(start, end)

    @safe_slot
    def _timeline_selection(self, start, end):
        """Trascinamento delle maniglie → campi IN/OUT."""
        self.in_time.setText(format_timestamp(start))
        self.out_time.setText(format_timestamp(end))

    @safe_slot
    def _skip(self, seconds):
        """Salto relativo dai pulsanti di trasporto."""
        if not self.player.is_running():
            self.statusBar().showMessage("Nessuna riproduzione in corso")
            return
        self.player.seek(seconds, "relative")

    @safe_slot
    def _timeline_seek(self, seconds):
        """Trascinamento della testina → salto nel video."""
        if self.player.is_running():
            self.player.seek(seconds)
        else:
            self.statusBar().showMessage(
                f"Posizione {format_timestamp(seconds)} (avvia la riproduzione per vederla)")

    # ------------------------------------------------------------- player

    def play_file(self):
        path = self.edit_file.text().strip()
        if not path:
            QMessageBox.warning(self, "ytEdit", "Nessuna sorgente da riprodurre.")
            return
        if not is_url(path) and not Path(path).exists():
            QMessageBox.warning(self, "ytEdit", f"File non trovato:\n{path}")
            return
        try:
            start = parse_timestamp(self.in_time.text())
        except FFmpegError:
            start = None
        # Il widget video crea il contesto OpenGL solo quando è visibile.
        self.tabs.setCurrentIndex(1)
        # In anteprima non serve il 4K: lo streaming resta fluido.
        fmt = build_format(self.quality.currentText()) if is_url(path) else None
        if is_url(path) and self.quality.currentText() == QUALITIES[0]:
            fmt = build_format("1080p")
        wid = None if self.video is not None else int(self.video_frame.winId())
        if self.player.play(path, wid=wid, start=start, ytdl_format=fmt):
            self._ipc_failures = 0
            self.position_timer.start()

    def stop_player(self):
        self.position_timer.stop()
        self.position_label.setText("--:--:--")
        self.player.stop()

    @safe_slot
    def _update_position(self):
        if not self.player.is_running():
            self.position_timer.stop()
            self.position_label.setText("--:--:--")
            return
        pos = self.player.time_pos()
        if pos is None:
            self._ipc_failures += 1
            if self._ipc_failures >= 3:
                self.position_timer.stop()
            return
        self._ipc_failures = 0
        self.position_label.setText(format_timestamp(pos))
        if not self.timeline.duration():
            self.timeline.set_duration(self.player.duration() or 0.0)
        self.timeline.set_position(pos)

    def _set_time_from_player(self, field: QLineEdit):
        pos = self.player.time_pos()
        if pos is None:
            QMessageBox.information(self, "ytEdit",
                                    "Nessuna riproduzione attiva da cui leggere la posizione.")
            return
        field.setText(format_timestamp(pos))

    @safe_slot
    def download_section(self):
        """Scarica dall'URL solo l'intervallo IN–OUT, senza prendere tutto."""
        source = self.edit_file.text().strip()
        if not is_url(source):
            QMessageBox.information(
                self, "ytEdit",
                "«Scarica IN–OUT» serve per una sorgente remota.\n"
                "Per un file locale già scaricato usa «✂ Taglia» nell'editor."
            )
            return
        self.section.setChecked(True)
        if self.selected_section() is None:
            QMessageBox.warning(self, "ytEdit",
                                "Intervallo non valido: controlla IN e OUT.")
            return
        self.url.setText(source)
        self.enqueue(start=True)

    # ------------------------------------------------------------ analisi

    @safe_slot
    def analyze(self):
        url = self.url.text().strip()
        if not url:
            self.log_line("Inserisci un URL prima di analizzare.")
            self.statusBar().showMessage("Nessun URL")
            return
        if self.analyze_worker and self.analyze_worker.isRunning():
            self.log_line("Analisi già in corso: attendi il termine.")
            self.statusBar().showMessage("Analisi già in corso")
            return
        self.url_info.setText("Analisi in corso…")
        self.statusBar().showMessage("Analisi in corso…")
        playlist = self.playlist.isChecked()
        self.log_line("$ " + shlex.join(analyze_command(url, playlist)))
        self.analyze_worker = AnalyzeWorker(url, playlist, self)
        self.analyze_worker.line.connect(self.log_line)
        self.analyze_worker.result.connect(self._analyze_done)
        self.analyze_worker.error.connect(self._analyze_failed)
        self.analyze_worker.start()

    @safe_slot
    def _analyze_done(self, data):
        title = data.get("title") or "(senza titolo)"
        if data.get("_type") == "playlist":
            entries = data.get("entries") or []
            summary = f"Playlist: {title} · {len(entries)} elementi"
        else:
            duration = data.get("duration")
            duration_text = format_timestamp(duration) if duration else "?"
            resolution = (f"{data.get('width')}×{data.get('height')}"
                          if data.get("width") else "?")
            summary = f"{title} · {duration_text} · {resolution} · {data.get('ext', '?')}"
        self.url_info.setText(summary)
        self.log_line(f"Analisi: {summary}")
        self.statusBar().showMessage("Analisi completata")

        if data.get("_type") == "playlist":
            return
        # L'URL diventa la sorgente dell'editor: si guarda in streaming e si
        # sceglie il segmento prima di scaricare qualsiasi cosa.
        self._remote_duration = float(data.get("duration") or 0.0)
        self._analyzed_url = self.analyze_worker.url if self.analyze_worker else ""
        self.edit_file.setText(self._analyzed_url)
        self.viewer_box.set_ratio(data.get("width"), data.get("height"))
        self.tabs.setCurrentIndex(1)
        # Nessuna riproduzione automatica: partire da soli a volume pieno è un
        # modo sicuro per far saltare sulla sedia chi ha le cuffie.
        self.statusBar().showMessage("Pronto: premi ▶ Riproduci per l'anteprima")
        if not self.player.available():
            self.log_line("mpv non disponibile: anteprima in streaming non possibile.")

    @safe_slot
    def _analyze_failed(self, message):
        self.url_info.setText("Analisi fallita.")
        self.log_line(f"ERRORE analisi: {message}")
        self.statusBar().showMessage("Analisi fallita")

    # --------------------------------------------------------------- coda

    def enqueue(self, start=True):
        url = self.url.text().strip()
        if not url:
            QMessageBox.warning(self, "ytEdit", "Inserisci un URL.")
            return
        outdir = Path(self.outdir.text().strip())
        try:
            outdir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "ytEdit", f"Cartella di destinazione non utilizzabile:\n{exc}")
            return
        job = Job(url=url, opts=self.download_options())
        self.jobs.append(job)
        self._refresh_queue()
        self.url.clear()
        self.url_info.clear()
        if start:
            self.queue_active = True
            self._start_next()
        else:
            self.statusBar().showMessage(f"In coda: {len(self.jobs)} elementi")

    def _refresh_queue(self):
        self.queue.clear()
        for job in self.jobs:
            self.queue.addItem(QListWidgetItem(job.label()))

    def remove_job(self):
        row = self.queue.currentRow()
        if row < 0 or row >= len(self.jobs):
            return
        if self.jobs[row] is self.active_job:
            QMessageBox.information(self, "ytEdit", "Interrompi il download prima di rimuoverlo.")
            return
        self.jobs.pop(row)
        self._refresh_queue()

    def clear_finished_jobs(self):
        self.jobs = [j for j in self.jobs if j.status in ("in attesa", "in corso")]
        self._refresh_queue()

    def _start_next(self):
        if not self.queue_active:
            return
        if self.download_worker and self.download_worker.isRunning():
            return
        job = next((j for j in self.jobs if j.status == "in attesa"), None)
        if job is None:
            self.active_job = None
            self.statusBar().showMessage("Coda completata")
            return

        job.status = "in corso"
        self.active_job = job
        self._refresh_queue()
        self.progress.setValue(0)
        self.statusBar().showMessage(f"Download: {job.url}")

        self.download_worker = YTDLPWorker(url=job.url, parent=self, **job.opts)
        self.download_worker.line.connect(self.log_line)
        self.download_worker.progress.connect(self.progress.setValue)
        self.download_worker.filepath.connect(self._downloaded_file)
        self.download_worker.result.connect(self._download_done)
        self.download_worker.error.connect(self._download_failed)
        self.download_worker.start()

    @safe_slot
    def _downloaded_file(self, path):
        if path and Path(path).exists():
            self.edit_file.setText(path)
            if self.active_job and not self.active_job.title:
                self.active_job.title = Path(path).name
                self._refresh_queue()

    @safe_slot
    def _download_done(self, path):
        self.progress.setValue(100)
        self.log_line("Download completato.")
        if self.active_job:
            self.active_job.status = "completato"
            if path:
                self.active_job.title = Path(path).name
        self._refresh_queue()
        self._start_next()

    @safe_slot
    def _download_failed(self, message):
        self.log_line(f"ERRORE download:\n{message}")
        if self.active_job:
            self.active_job.status = "interrotto" if not self.queue_active else "errore"
        self._refresh_queue()
        self._start_next()

    def stop_download(self):
        self.queue_active = False
        if self.download_worker and self.download_worker.isRunning():
            self.download_worker.stop()
        for job in self.jobs:
            if job.status == "in attesa":
                job.status = "interrotto"
        self._refresh_queue()
        self.statusBar().showMessage("Coda interrotta")

    # ------------------------------------------------------------- FFmpeg

    def _busy(self) -> bool:
        if self.process_worker and self.process_worker.isRunning():
            QMessageBox.information(self, "ytEdit", "Un'operazione FFmpeg è già in corso.")
            return True
        return False

    def run_ffmpeg(self, args, total_duration=0.0, output=None, operation=""):
        if self._busy():
            return
        self._pending_output = output
        self._pending_op = operation or "Operazione"
        self.cmd_preview.setPlainText(self._render_command(args))
        self.log_line(f"$ {shlex.join(str(a) for a in args)}")
        self.progress.setValue(0)
        self.statusBar().showMessage(f"{self._pending_op} in corso…")

        self.process_worker = ProcessWorker(args, total_duration=total_duration, parent=self)
        self.process_worker.output.connect(self.log_line)
        self.process_worker.progress.connect(self.progress.setValue)
        self.process_worker.finished_ok.connect(self._ffmpeg_finished)
        self.process_worker.start()

    @safe_slot
    def _ffmpeg_finished(self, code, last_line):
        self._cleanup_temp_files()
        if code == 0:
            self.progress.setValue(100)
            output = self._pending_output
            self.log_line(f"✔ {self._pending_op} completata: {output or ''}")
            self.statusBar().showMessage(f"{self._pending_op} completata")
            if output and Path(output).exists():
                self.edit_file.setText(output)
        elif code == -2:
            self.log_line("⏹ Operazione interrotta.")
            self.statusBar().showMessage("Operazione interrotta")
        else:
            self.log_line(f"✖ {self._pending_op} fallita (codice {code}): {last_line}")
            self.statusBar().showMessage(f"{self._pending_op} fallita")
            QMessageBox.warning(self, "ytEdit",
                                f"{self._pending_op} fallita (codice {code}).\n\n{last_line}")
        self._pending_output = None

    def stop_ffmpeg(self):
        if self.process_worker and self.process_worker.isRunning():
            self.process_worker.stop()

    def _cleanup_temp_files(self):
        for path in self._temp_files:
            try:
                path.unlink()
            except OSError:
                pass
        self._temp_files.clear()

    def _guard(self, build):
        """Esegue un builder di comandi mostrando gli errori di configurazione."""
        try:
            return build()
        except FFmpegError as exc:
            QMessageBox.warning(self, "ytEdit", str(exc))
        except OSError as exc:
            QMessageBox.warning(self, "ytEdit", str(exc))
        return None

    def cut(self):
        src = self.source_file()
        if not src:
            return
        dst = self.output_path("_cut")
        args = self._guard(lambda: cut_cmd(src, dst, self.in_time.text(),
                                           self.out_time.text(), self.precise.isChecked()))
        if not args:
            return
        duration = parse_timestamp(self.out_time.text()) - parse_timestamp(self.in_time.text())
        self.run_ffmpeg(args, total_duration=duration, output=dst, operation="Taglio")

    @safe_slot
    def remove_section(self):
        """Elimina l'intervallo selezionato e ricuce il resto."""
        src = self.source_file()
        if not src:
            return
        dst = self.output_path("_senza_selezione")
        args = self._guard(lambda: remove_section_cmd(src, dst, self.in_time.text(),
                                                      self.out_time.text()))
        if not args:
            return
        self.run_ffmpeg(args, total_duration=media_info(src).duration,
                        output=dst, operation="Rimozione selezione")

    def transform(self):
        src = self.source_file()
        if not src:
            return
        dst = self.output_path("_edited")
        args = self._guard(lambda: transform_cmd(
            src, dst, self.scale_width.text(), self.scale_height.text(), self.rotate.currentText(),
            str(self.volume.value()), self.fadein.text(), self.fadeout.text()))
        if not args:
            return
        self.run_ffmpeg(args, total_duration=media_info(src).duration,
                        output=dst, operation="Trasformazione")

    def extract_audio(self):
        src = self.source_file()
        if not src:
            return
        dst, _ = QFileDialog.getSaveFileName(
            self, "Salva audio", str(Path(src).with_suffix(".flac")),
            "FLAC (*.flac);;MP3 (*.mp3);;WAV (*.wav);;M4A (*.m4a);;Opus (*.opus)")
        if not dst:
            return
        codec = Path(dst).suffix.lower().lstrip(".")
        args = self._guard(lambda: extract_audio_cmd(src, dst, codec))
        if args:
            self.run_ffmpeg(args, total_duration=media_info(src).duration,
                            output=None, operation="Estrazione audio")

    def replace_audio(self):
        video = self.source_file()
        if not video:
            return
        audio, _ = QFileDialog.getOpenFileName(self, "Seleziona audio", str(Path.home()))
        if not audio:
            return
        dst = self.output_path("_newaudio")
        args = self._guard(lambda: replace_audio_cmd(video, audio, dst))
        if args:
            self.run_ffmpeg(args, total_duration=media_info(video).duration,
                            output=dst, operation="Sostituzione audio")

    # --------------------------------------------------------- sottotitoli

    def burn_subtitles(self):
        src = self.source_file()
        if not src:
            return
        sub = self.sub_file.text().strip()
        if not sub:
            QMessageBox.warning(self, "ytEdit", "Seleziona un file di sottotitoli.")
            return
        dst = self.output_path("_sub")
        args = self._guard(lambda: burn_subtitles_cmd(src, sub, dst))
        if args:
            self.run_ffmpeg(args, total_duration=media_info(src).duration,
                            output=dst, operation="Masterizzazione sottotitoli")

    def mux_subtitles(self):
        src = self.source_file()
        if not src:
            return
        sub = self.sub_file.text().strip()
        if not sub:
            QMessageBox.warning(self, "ytEdit", "Seleziona un file di sottotitoli.")
            return
        dst = self.output_path("_subbed", ext=".mkv")
        args = self._guard(lambda: mux_subtitles_cmd(src, sub, dst))
        if args:
            self.run_ffmpeg(args, total_duration=media_info(src).duration,
                            output=dst, operation="Incorporazione sottotitoli")

    # --------------------------------------------------------------- unione

    def add_concat_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Seleziona i file da unire", str(Path.home()))
        for f in files:
            self.concat_list.addItem(QListWidgetItem(f))

    def remove_concat_file(self):
        row = self.concat_list.currentRow()
        if row >= 0:
            self.concat_list.takeItem(row)

    def move_concat_file(self, delta):
        row = self.concat_list.currentRow()
        target = row + delta
        if row < 0 or not (0 <= target < self.concat_list.count()):
            return
        item = self.concat_list.takeItem(row)
        self.concat_list.insertItem(target, item)
        self.concat_list.setCurrentRow(target)

    def concat_files(self) -> list[str]:
        return [self.concat_list.item(i).text() for i in range(self.concat_list.count())]

    def concat(self):
        paths = self.concat_files()
        if len(paths) < 2:
            QMessageBox.warning(self, "ytEdit", "Aggiungi almeno due file da unire.")
            return
        missing = [p for p in paths if not Path(p).exists()]
        if missing:
            QMessageBox.warning(self, "ytEdit", "File non trovati:\n" + "\n".join(missing))
            return

        default = str(Path(paths[0]).with_name(Path(paths[0]).stem + "_unito" + Path(paths[0]).suffix))
        dst, _ = QFileDialog.getSaveFileName(self, "Salva file unito", default)
        if not dst:
            return

        if self.concat_reencode.isChecked():
            args = self._guard(lambda: concat_encode_cmd(paths, dst))
        else:
            handle = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
            handle.close()
            list_path = Path(handle.name)
            self._temp_files.append(list_path)
            args = self._guard(lambda: concat_copy_cmd(write_concat_list(paths, list_path), dst))
        if not args:
            self._cleanup_temp_files()
            return
        total = sum(media_info(p).duration for p in paths)
        self.run_ffmpeg(args, total_duration=total, output=dst, operation="Unione")

    # ---------------------------------------------------------- anteprima

    @staticmethod
    def _render_command(args) -> str:
        return shlex.join(str(a) for a in args)

    @safe_slot
    def _update_preview(self):
        if not hasattr(self, "cmd_preview"):
            return
        blocks = []

        url = self.url.text().strip() or "<URL>"
        blocks.append("# yt-dlp\n"
                      + self._render_command(build_command(url, **self.download_options())))

        src = self.edit_file.text().strip()
        if is_url(src):
            section = self.selected_section()
            blocks.append("# editor\n⚠ Sorgente remota in streaming: gli strumenti FFmpeg "
                          "lavorano su file locali.\n"
                          + (f"Selezione attiva: {section[0]} → {section[1]}."
                             if section else
                             "Attiva «Solo selezione IN–OUT» per scaricare solo il segmento."))
        elif src:
            for title, build in (
                ("taglio", lambda: cut_cmd(src, self.output_path("_cut"), self.in_time.text(),
                                           self.out_time.text(), self.precise.isChecked())),
                ("trasformazione", lambda: transform_cmd(
                    src, self.output_path("_edited"), self.scale_width.text(), self.scale_height.text(),
                    self.rotate.currentText(), str(self.volume.value()),
                    self.fadein.text(), self.fadeout.text())),
            ):
                try:
                    blocks.append(f"# {title}\n" + self._render_command(build()))
                except FFmpegError as exc:
                    blocks.append(f"# {title}\n⚠ {exc}")
                except OSError as exc:
                    blocks.append(f"# {title}\n⚠ {exc}")
        else:
            blocks.append("# editor\n⚠ Nessun file selezionato nell'editor.")

        self.cmd_preview.setPlainText("\n\n".join(blocks))

    # ------------------------------------------------------------ chiusura

    def closeEvent(self, event):
        self.queue_active = False
        self.position_timer.stop()
        for worker in (self.download_worker, self.process_worker):
            if worker and worker.isRunning():
                worker.stop()
                worker.wait(5000)
        if self.analyze_worker and self.analyze_worker.isRunning():
            self.analyze_worker.stop()
            self.analyze_worker.wait(3000)
        self.player.stop()
        if self.video is not None:
            self.video.shutdown()
        self._cleanup_temp_files()
        self._save_settings()
        super().closeEvent(event)
