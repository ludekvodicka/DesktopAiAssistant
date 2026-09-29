from PySide6.QtCore import QMimeData
from PySide6.QtGui import QGuiApplication, QImage
import pythoncom
import win32clipboard


def copy_mime_data(source):
    saved = QMimeData()
    if source is None:
        return saved
    for name in source.formats():
        if name == "application/x-qt-image":
            image = QImage(source.imageData()).copy()
            if image.isNull():
                raise RuntimeError("Could not preserve the clipboard image. No text was inserted.")
            saved.setImageData(image)
        else:
            saved.setData(name, source.data(name))
    return saved


class Clipboard:
    app: QGuiApplication
    clipboard: object

    def __init__(self):
        self.app = QGuiApplication.instance() or QGuiApplication([])
        self.clipboard = self.app.clipboard()

    def replace(self, text):
        sequence = win32clipboard.GetClipboardSequenceNumber()
        # OleGetClipboard returns a live proxy, not a backup of its data.
        saved = copy_mime_data(self.clipboard.mimeData())
        if win32clipboard.GetClipboardSequenceNumber() != sequence:
            raise RuntimeError("The clipboard changed. No text was inserted.")
        self.clipboard.setText(text)
        if not self.clipboard.ownsClipboard():
            raise RuntimeError("Could not prepare the clipboard. No text was inserted.")
        pythoncom.OleFlushClipboard()
        sequence = win32clipboard.GetClipboardSequenceNumber()
        self.app.processEvents()
        if win32clipboard.GetClipboardSequenceNumber() != sequence:
            raise RuntimeError("The clipboard changed. No text was inserted.")
        return saved, sequence

    def restore(self, saved, sequence):
        if win32clipboard.GetClipboardSequenceNumber() != sequence:
            return
        self.clipboard.setMimeData(saved)
        if not self.clipboard.ownsClipboard():
            raise RuntimeError("Could not restore the clipboard")
        # Render our independent copy while the worker is alive.
        pythoncom.OleFlushClipboard()
        self.app.processEvents()
