import time
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMimeData, Qt
from PySide6.QtGui import QGuiApplication, QImage, QTextDocument
import pythoncom
import win32clipboard
from .text import clean_markdown

EXCLUDE = 'application/x-qt-windows-mime;value="ExcludeClipboardContentFromMonitorProcessing"'


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


def markdown_from_html(html):
    document = QTextDocument()
    document.setHtml(html)
    return clean_markdown(document.toMarkdown())


def image_png(image):
    if image.isNull():
        raise RuntimeError("The image could not be read")
    if max(image.width(), image.height()) > 2000:
        image = image.scaled(2000, 2000, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    for step in range(5):
        if step:
            image = image.scaled(round(image.width() * 0.75), round(image.height() * 0.75), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        image.save(buffer, "PNG")
        if buffer.size() <= 3_500_000:
            return bytes(buffer.data())
    raise RuntimeError("The image is too large")


def source_from_mime(mime, kind, origin, empty):
    # Huge HTML (a whole page) takes long to convert and exceeds the text limit anyway; the plain text gives the clear size error.
    if mime is not None and mime.hasHtml() and len(mime.html()) <= 1_000_000:
        text = markdown_from_html(mime.html())
        if text.strip():
            return {"kind": kind, "format": "markdown", "text": text, "image": None, "origin": origin}
    # Qt 6 hasText() is also true for file URLs alone.
    if mime is not None and mime.hasFormat("text/plain") and mime.text().strip():
        return {"kind": kind, "format": "plain", "text": mime.text(), "image": None, "origin": origin}
    if mime is not None and mime.hasImage():
        return {"kind": kind, "format": "image", "text": "", "image": image_png(QImage(mime.imageData())), "origin": origin}
    raise RuntimeError(empty)


class Clipboard:
    app: QGuiApplication
    clipboard: object

    def __init__(self):
        self.app = QGuiApplication.instance() or QGuiApplication([])
        self.clipboard = self.app.clipboard()

    def backup(self):
        sequence = win32clipboard.GetClipboardSequenceNumber()
        # OleGetClipboard returns a live proxy, not a backup of its data.
        saved = copy_mime_data(self.clipboard.mimeData())
        if win32clipboard.GetClipboardSequenceNumber() != sequence:
            raise RuntimeError("The clipboard changed during the backup. Try again.")
        return saved, sequence

    def replace(self, text):
        saved, _ = self.backup()
        self.clipboard.setText(text)
        if not self.clipboard.ownsClipboard():
            raise RuntimeError("Could not prepare the clipboard. No text was inserted.")
        pythoncom.OleFlushClipboard()
        sequence = win32clipboard.GetClipboardSequenceNumber()
        self.app.processEvents()
        if win32clipboard.GetClipboardSequenceNumber() != sequence:
            raise RuntimeError("The clipboard changed. No text was inserted.")
        return saved, sequence

    def wait_change(self, sequence, timeout):
        deadline = time.monotonic() + timeout
        current, since = sequence, time.monotonic()
        while time.monotonic() < deadline:
            self.app.processEvents()
            latest = win32clipboard.GetClipboardSequenceNumber()
            if latest != current:
                current, since = latest, time.monotonic()
            # Some applications write their formats in several steps.
            elif current != sequence and time.monotonic() - since >= 0.06:
                break
            time.sleep(0.01)
        return current

    def restore(self, saved, sequence):
        if win32clipboard.GetClipboardSequenceNumber() != sequence:
            return
        # Win+V history keeps no duplicate of the restored item.
        saved.setData(EXCLUDE, QByteArray(b"\0\0\0\0"))
        self.clipboard.setMimeData(saved)
        if not self.clipboard.ownsClipboard():
            raise RuntimeError("Could not restore the clipboard")
        # Render our independent copy while the worker is alive.
        pythoncom.OleFlushClipboard()
        self.app.processEvents()
