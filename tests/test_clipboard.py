from types import SimpleNamespace
import pytest
from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtGui import QGuiApplication, QImage, QColor
from desktop_ai_assistant.clipboard import Clipboard, copy_mime_data
from desktop_ai_assistant import clipboard as clipboard_module


@pytest.fixture
def app():
    return QGuiApplication.instance() or QGuiApplication([])


def test_backup_survives_destruction_of_original_mime_data(app):
    import shiboken6
    source = QMimeData()
    source.setText("original text")
    source.setHtml("<b>original text</b>")
    source.setUrls([QUrl("https://example.com/demo")])
    source.setData('application/x-qt-windows-mime;value="ExampleFormat"', b"\x00\x01sample")
    image = QImage(3, 2, QImage.Format_ARGB32)
    image.fill(QColor("#34ab56"))
    source.setImageData(image)
    saved = copy_mime_data(source)
    shiboken6.delete(source)
    assert saved.text() == "original text"
    assert saved.html() == "<b>original text</b>"
    assert saved.urls() == [QUrl("https://example.com/demo")]
    assert bytes(saved.data('application/x-qt-windows-mime;value="ExampleFormat"')) == b"\x00\x01sample"
    assert saved.imageData().pixelColor(1, 1) == QColor("#34ab56")


def test_empty_clipboard_has_an_independent_backup(app):
    assert copy_mime_data(None).formats() == []


def test_newer_clipboard_content_is_not_overwritten(monkeypatch):
    clipboard = Clipboard.__new__(Clipboard)
    clipboard.clipboard = None
    monkeypatch.setattr(clipboard_module.win32clipboard, "GetClipboardSequenceNumber", lambda: 11)
    clipboard.restore(QMimeData(), 10)


def test_changed_clipboard_during_backup_prevents_insertion(app, monkeypatch):
    sequence = iter([10, 11])
    clipboard = Clipboard.__new__(Clipboard)
    clipboard.clipboard = SimpleNamespace(mimeData=QMimeData)
    monkeypatch.setattr(clipboard_module.win32clipboard, "GetClipboardSequenceNumber", lambda: next(sequence))
    with pytest.raises(RuntimeError, match="clipboard changed"):
        clipboard.replace("must not be inserted")
