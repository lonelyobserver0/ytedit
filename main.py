import sys

from ytedit import video_widget
from ytedit.qtplatform import prefer_x11_for_embedding

# Il player integrato renderizza dentro il widget e funziona su Wayland nativo:
# solo se manca (niente python-mpv/libmpv) si ripiega su mpv esterno, che per
# incorporarsi ha bisogno di una finestra X11.
if not video_widget.is_available():
    prefer_x11_for_embedding()

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ytedit import theme  # noqa: E402
from ytedit.main_window import MainWindow  # noqa: E402

app = QApplication(sys.argv)
app.setApplicationName("ytEdit")
app.setOrganizationName("ytEdit")
theme.apply(app, QSettings("ytEdit", "ytEdit").value("ui/theme", "scuro"))
window = MainWindow()
window.show()
sys.exit(app.exec())
