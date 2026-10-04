"""
Qt for both Krita lines: Krita 5.x ships PyQt5, Krita 6 ships PyQt6.

Everything else imports Qt from here. The differences that matter to this plugin:
- PyQt6 only has scoped enums (Qt.AlignmentFlag.AlignLeft); PyQt5 accepts both forms for
  most enums, so the code uses the scoped form and `E()` for the rest;
- QAction/QShortcut moved from QtWidgets to QtGui;
- exec_() is exec() in PyQt6.
"""
from __future__ import annotations

try:  # Krita 6
    from PyQt6 import QtCore, QtGui, QtWidgets  # type: ignore
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QPoint, QRect, QSize, Qt, QTimer, QUrl, QUuid, pyqtSignal  # type: ignore
    from PyQt6.QtGui import QAction, QColor, QDesktopServices, QIcon, QImage, QPainter, QPixmap  # type: ignore
    from PyQt6.QtWidgets import (  # type: ignore
        QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
        QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
        QStackedWidget, QTabWidget, QTextEdit, QToolButton, QVBoxLayout, QWidget,
    )

    PYQT = 6
except ImportError:  # Krita 5
    from PyQt5 import QtCore, QtGui, QtWidgets  # type: ignore
    from PyQt5.QtCore import QBuffer, QByteArray, QIODevice, QObject, QPoint, QRect, QSize, Qt, QTimer, QUrl, QUuid, pyqtSignal  # type: ignore
    from PyQt5.QtGui import QColor, QDesktopServices, QIcon, QImage, QPainter, QPixmap  # type: ignore
    from PyQt5.QtWidgets import (  # type: ignore
        QAbstractItemView, QAction, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QGroupBox,
        QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
        QSpinBox, QStackedWidget, QTabWidget, QTextEdit, QToolButton, QVBoxLayout, QWidget,
    )

    PYQT = 5


def E(owner: object, scoped: str, name: str):
    """An enum value by its scoped name in both PyQt5 and PyQt6: E(Qt, "AlignmentFlag", "AlignLeft")."""
    scope = getattr(owner, scoped, None)
    if scope is not None and hasattr(scope, name):
        return getattr(scope, name)
    return getattr(owner, name)


def exec_(obj, *args):
    """dialog.exec() / menu.exec(pos): exec_ in older PyQt5."""
    return obj.exec(*args) if hasattr(obj, "exec") else obj.exec_(*args)


def image_to_png(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(E(QIODevice, "OpenModeFlag", "WriteOnly"))
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def image_bytes(image: QImage) -> bytes:
    """The raw pixels of a 32-bit QImage, row by row without padding."""
    ptr = image.constBits()
    ptr.setsize(image.sizeInBytes() if hasattr(image, "sizeInBytes") else image.byteCount())
    data = bytes(ptr)
    stride = image.bytesPerLine()
    row = image.width() * 4
    if stride == row:
        return data
    return b"".join(data[y * stride : y * stride + row] for y in range(image.height()))
