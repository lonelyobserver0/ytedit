import sys
from PySide6.QtWidgets import QApplication
from ytedit.main_window import MainWindow

app = QApplication(sys.argv)
app.setApplicationName("ytEdit")
app.setOrganizationName("ytEdit")
window = MainWindow()
window.show()
sys.exit(app.exec())
