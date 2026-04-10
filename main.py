"""BioTrace — Application Entry Point.

Run this file to start the BioTrace desktop application:
    python main.py
"""

import sys

import signal

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QFontDatabase, QFont
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWidgets import QPushButton

from app.ui.main_window import MainWindow
from app.utils.logger import get_logger

logger = get_logger(__name__)


class _PointerCursorFilter(QObject):
    """Global event filter to enforce pointer cursor on button hover."""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if isinstance(obj, QPushButton):
            if event.type() == QEvent.Type.Enter and obj.isEnabled():
                obj.setCursor(Qt.CursorShape.PointingHandCursor)
            elif event.type() in (QEvent.Type.Leave, QEvent.Type.EnabledChange):
                if obj.isEnabled():
                    obj.unsetCursor()
                else:
                    obj.setCursor(Qt.CursorShape.ArrowCursor)
        return super().eventFilter(obj, event)


def main() -> None:
    """Create the QApplication, apply global font, and show the main window."""
    # Signal-Handler für SIGINT (Ctrl+C), damit das Programm sauber beendet wird
    signal.signal(signal.SIGINT, lambda sig, frame: QApplication.quit())
    app = QApplication(sys.argv)
    app.setApplicationName("BioTrace")
    app.setOrganizationName("TSS Lab")

    # Use Inter if available, otherwise fall back to the system sans-serif font.
    font = QFont("Inter", 10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)

    # Ensure all QPushButton widgets use pointer cursor on hover app-wide.
    pointer_cursor_filter = _PointerCursorFilter(app)
    app.installEventFilter(pointer_cursor_filter)
    app._pointer_cursor_filter = pointer_cursor_filter

    window = MainWindow()
    app.aboutToQuit.connect(window.cleanup)
    window.show()

    logger.info("BioTrace started.")
    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
