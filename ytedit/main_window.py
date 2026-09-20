from pathlib import Path
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QCheckBox, QProgressBar,
    QTextEdit, QFileDialog, QListWidget, QListWidgetItem, QGroupBox,
    QTabWidget, QDoubleSpinBox, QSpinBox, QMessageBox
)
from .downloader import YTDLPWorker
from .workers import ProcessWorker
from .ffmpeg import cut_cmd, extract_audio_cmd, transform_cmd, replace_audio_cmd
from .player import MPVPlayer

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ytEdit — yt-dlp + FFmpeg")
        self.resize(1200, 800)
        self.settings = QSettings("ytEdit", "ytEdit")
        self.download_worker = None
        self.process_worker = None
        self.player = MPVPlayer()
        self.current_file = None
        self._build()

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        urlrow = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setPlaceholderText("URL YouTube / Vimeo / sito supportato da yt-dlp…")
        analyze = QPushButton("Analizza")
        analyze.clicked.connect(self.analyze)
        urlrow.addWidget(self.url, 1)
        urlrow.addWidget(analyze)
        layout.addLayout(urlrow)

        tabs = QTabWidget()
        tabs.addTab(self._download_tab(), "Download")
        tabs.addTab(self._edit_tab(), "Editor")
        tabs.addTab(self._advanced_tab(), "Avanzato")
        layout.addWidget(tabs, 1)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(180)
        layout.addWidget(QLabel("Log"))
        layout.addWidget(self.log)

    def _download_tab(self):
        w = QWidget(); g = QGridLayout(w)
        g.addWidget(QLabel("Qualità"), 0, 0)
        self.quality = QComboBox()
        self.quality.addItems(["Best disponibile", "1080p", "720p", "480p", "360p"])
        g.addWidget(self.quality, 0, 1)

        g.addWidget(QLabel("Formato"), 1, 0)
        self.format = QComboBox()
        self.format.addItems(["MP4", "MKV", "WEBM"])
        g.addWidget(self.format, 1, 1)

        self.audio_only = QCheckBox("Solo audio (MP3)")
        self.subs = QCheckBox("Scarica sottotitoli")
        g.addWidget(self.audio_only, 2, 0)
        g.addWidget(self.subs, 2, 1)

        self.outdir = QLineEdit(str(Path.home() / "Downloads"))
        browse = QPushButton("Sfoglia…")
        browse.clicked.connect(self.choose_dir)
        g.addWidget(QLabel("Destinazione"), 3, 0)
        g.addWidget(self.outdir, 3, 1)
        g.addWidget(browse, 3, 2)

        row = QHBoxLayout()
        download = QPushButton("Scarica")
        download.clicked.connect(self.download)
        stop = QPushButton("Interrompi")
        stop.clicked.connect(self.stop_download)
        row.addWidget(download); row.addWidget(stop)
        g.addLayout(row, 4, 0, 1, 3)

        self.progress = QProgressBar()
        g.addWidget(self.progress, 5, 0, 1, 3)

        g.addWidget(QLabel("Coda"), 6, 0)
        self.queue = QListWidget()
        g.addWidget(self.queue, 7, 0, 1, 3)
        return w

    def _edit_tab(self):
        w = QWidget(); g = QGridLayout(w)

        file_row = QHBoxLayout()
        self.edit_file = QLineEdit()
        browse = QPushButton("Apri…")
        browse.clicked.connect(self.choose_edit_file)
        play = QPushButton("▶ Riproduci")
        play.clicked.connect(self.play_file)
        file_row.addWidget(self.edit_file, 1)
        file_row.addWidget(browse)
        file_row.addWidget(play)
        g.addLayout(file_row, 0, 0, 1, 4)

        cutbox = QGroupBox("Taglio")
        cg = QGridLayout(cutbox)
        self.in_time = QLineEdit("00:00:00")
        self.out_time = QLineEdit("00:00:10")
        self.precise = QCheckBox("Taglio preciso (ricodifica)")
        self.precise.setChecked(True)
        cut = QPushButton("✂ Taglia")
        cut.clicked.connect(self.cut)
        cg.addWidget(QLabel("IN"), 0, 0); cg.addWidget(self.in_time, 0, 1)
        cg.addWidget(QLabel("OUT"), 1, 0); cg.addWidget(self.out_time, 1, 1)
        cg.addWidget(self.precise, 2, 0, 1, 2)
        cg.addWidget(cut, 3, 0, 1, 2)
        g.addWidget(cutbox, 1, 0, 1, 2)

        trans = QGroupBox("Video / Audio")
        tg = QGridLayout(trans)
        self.width = QLineEdit()
        self.height = QLineEdit()
        self.rotate = QComboBox(); self.rotate.addItems(["none", "90", "180", "270"])
        self.volume = QDoubleSpinBox(); self.volume.setRange(0, 5); self.volume.setValue(1.0); self.volume.setSingleStep(.1)
        self.fadein = QLineEdit()
        self.fadeout = QLineEdit()
        for r, (name, widget) in enumerate([
            ("Larghezza", self.width), ("Altezza", self.height),
            ("Rotazione", self.rotate), ("Volume", self.volume),
            ("Fade in (s)", self.fadein), ("Fade out (s)", self.fadeout)]):
            tg.addWidget(QLabel(name), r, 0); tg.addWidget(widget, r, 1)
        transform = QPushButton("Applica trasformazioni")
        transform.clicked.connect(self.transform)
        tg.addWidget(transform, 6, 0, 1, 2)
        g.addWidget(trans, 1, 2, 1, 2)

        audio = QGroupBox("Audio")
        ag = QGridLayout(audio)
        extract = QPushButton("Estrai audio")
        extract.clicked.connect(self.extract_audio)
        replace = QPushButton("Sostituisci traccia audio")
        replace.clicked.connect(self.replace_audio)
        ag.addWidget(extract, 0, 0); ag.addWidget(replace, 0, 1)
        g.addWidget(audio, 2, 0, 1, 4)
        return w

    def _advanced_tab(self):
        w = QWidget(); g = QVBoxLayout(w)
        self.extra = QTextEdit()
        self.extra.setPlaceholderText("Argomenti extra yt-dlp, uno per riga…")
        g.addWidget(QLabel("Argomenti yt-dlp"))
        g.addWidget(self.extra)
        self.cmd_preview = QTextEdit()
        self.cmd_preview.setReadOnly(True)
        g.addWidget(QLabel("Anteprima comando FFmpeg"))
        g.addWidget(self.cmd_preview)
        return w

    def choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Cartella destinazione", self.outdir.text())
        if d: self.outdir.setText(d)

    def choose_edit_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "Apri media", str(Path.home()))
        if f:
            self.edit_file.setText(f)
            self.current_file = f

    def play_file(self):
        f = self.edit_file.text().strip()
        if f: self.player.play(f)

    def analyze(self):
        u = self.url.text().strip()
        if not u:
            return
        self.queue.addItem(QListWidgetItem(f"Analisi: {u}"))
        import subprocess, sys
        try:
            p = subprocess.run([sys.executable, "-m", "yt_dlp", "--dump-single-json", "--skip-download", u],
                               capture_output=True, text=True, timeout=60)
            if p.returncode:
                self.log.append(p.stderr)
                return
            import json
            data = json.loads(p.stdout)
            self.log.append(f"TITOLO: {data.get('title')}")
            self.log.append(f"DURATA: {data.get('duration')} s")
            self.log.append(f"RISOLUZIONE: {data.get('width')}x{data.get('height')}")
            self.log.append(f"FORMATO: {data.get('ext')}")
        except Exception as e:
            self.log.append(str(e))

    def download(self):
        u = self.url.text().strip()
        if not u:
            QMessageBox.warning(self, "ytEdit", "Inserisci un URL.")
            return
        fmt = "bestvideo+bestaudio/best"
        if self.quality.currentText() == "1080p":
            fmt = "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
        elif self.quality.currentText() == "720p":
            fmt = "bestvideo[height<=720]+bestaudio/best[height<=720]"
        elif self.quality.currentText() == "480p":
            fmt = "bestvideo[height<=480]+bestaudio/best[height<=480]"
        elif self.quality.currentText() == "360p":
            fmt = "bestvideo[height<=360]+bestaudio/best[height<=360]"
        self.download_worker = YTDLPWorker(u, self.outdir.text(), fmt,
                                           self.audio_only.isChecked(), self.subs.isChecked())
        self.download_worker.line.connect(self.log.append)
        self.download_worker.result.connect(lambda x: self.download_done(x))
        self.download_worker.error.connect(lambda x: self.log.append("ERRORE:\n" + x))
        self.download_worker.start()

    def download_done(self, text):
        self.progress.setValue(100)
        self.log.append("Download completato.")
        for line in reversed(text.splitlines()):
            if line.strip().startswith("/") and Path(line.strip()).exists():
                self.edit_file.setText(line.strip())
                self.current_file = line.strip()
                break

    def stop_download(self):
        if self.download_worker:
            self.download_worker.stop()

    def run_ffmpeg(self, args):
        self.cmd_preview.setPlainText(" ".join(f'"{a}"' if " " in a else a for a in args))
        self.process_worker = ProcessWorker(args)
        self.process_worker.output.connect(self.log.append)
        self.process_worker.progress.connect(self.progress.setValue)
        self.process_worker.start()

    def output_path(self, suffix):
        src = Path(self.edit_file.text())
        return str(src.with_name(src.stem + suffix + ".mp4"))

    def cut(self):
        src = self.edit_file.text().strip()
        if not src: return
        dst = self.output_path("_cut")
        args = cut_cmd(src, dst, self.in_time.text(), self.out_time.text(), self.precise.isChecked())
        self.run_ffmpeg(args)

    def transform(self):
        src = self.edit_file.text().strip()
        if not src: return
        dst = self.output_path("_edited")
        args = transform_cmd(src, dst, self.width.text(), self.height.text(),
                             self.rotate.currentText(), str(self.volume.value()),
                             self.fadein.text(), self.fadeout.text())
        self.run_ffmpeg(args)

    def extract_audio(self):
        src = self.edit_file.text().strip()
        if not src: return
        dst, _ = QFileDialog.getSaveFileName(self, "Salva audio", str(Path(src).with_suffix(".flac")),
                                             "FLAC (*.flac);;MP3 (*.mp3);;WAV (*.wav)")
        if not dst: return
        codec = Path(dst).suffix.lower().lstrip(".")
        self.run_ffmpeg(extract_audio_cmd(src, dst, codec))

    def replace_audio(self):
        video = self.edit_file.text().strip()
        if not video: return
        audio, _ = QFileDialog.getOpenFileName(self, "Seleziona audio", str(Path.home()))
        if not audio: return
        dst = self.output_path("_newaudio")
        self.run_ffmpeg(replace_audio_cmd(video, audio, dst))
