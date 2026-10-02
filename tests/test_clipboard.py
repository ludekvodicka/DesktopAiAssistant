import os
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtGui import QGuiApplication, QImage, QColor
from desktop_ai_assistant.clipboard import Clipboard, copy_mime_data, source_from_mime, image_png, EXCLUDE
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


class FakeQtClipboard:
    published: list

    def __init__(self):
        self.published = []

    def setMimeData(self, data):
        self.published.append(data)

    def ownsClipboard(self):
        return True


def test_newer_clipboard_content_is_not_overwritten(app, monkeypatch):
    clipboard = Clipboard.__new__(Clipboard)
    clipboard.clipboard = FakeQtClipboard()
    monkeypatch.setattr(clipboard_module.win32clipboard, "GetClipboardSequenceNumber", lambda: 11)
    saved = QMimeData()
    clipboard.restore(saved, 10)
    assert clipboard.clipboard.published == []
    assert not saved.hasFormat(EXCLUDE)


def test_restore_is_excluded_from_clipboard_history(app, monkeypatch):
    clipboard = Clipboard.__new__(Clipboard)
    clipboard.app = app
    clipboard.clipboard = FakeQtClipboard()
    monkeypatch.setattr(clipboard_module.win32clipboard, "GetClipboardSequenceNumber", lambda: 10)
    monkeypatch.setattr(clipboard_module.pythoncom, "OleFlushClipboard", lambda: None)
    saved = QMimeData()
    saved.setText("previous synthetic text")
    clipboard.restore(saved, 10)
    assert clipboard.clipboard.published == [saved]
    assert saved.text() == "previous synthetic text"
    assert bytes(saved.data(EXCLUDE)) == b"\0\0\0\0"


def test_wait_change_returns_the_settled_sequence(app, monkeypatch):
    clipboard = Clipboard.__new__(Clipboard)
    clipboard.app = app
    monkeypatch.setattr(clipboard_module.win32clipboard, "GetClipboardSequenceNumber", lambda: 10)
    assert clipboard.wait_change(10, 0.1) == 10
    sequence = iter([11, 12] + [13] * 1000)
    monkeypatch.setattr(clipboard_module.win32clipboard, "GetClipboardSequenceNumber", lambda: next(sequence))
    assert clipboard.wait_change(10, 1.0) == 13


def test_changed_clipboard_during_backup_prevents_insertion(app, monkeypatch):
    sequence = iter([10, 11])
    clipboard = Clipboard.__new__(Clipboard)
    clipboard.clipboard = SimpleNamespace(mimeData=QMimeData)
    monkeypatch.setattr(clipboard_module.win32clipboard, "GetClipboardSequenceNumber", lambda: next(sequence))
    with pytest.raises(RuntimeError, match="clipboard changed"):
        clipboard.replace("must not be inserted")


def test_html_becomes_markdown_without_images(app):
    mime = QMimeData()
    mime.setHtml("<h1>Report</h1><ul><li>first</li><li>second</li></ul><table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
                 "<p>See <a href='https://example.com/page'>the page</a> <img src='https://example.com/a.png' alt='chart'></p>")
    mime.setText("Report first second")
    source = source_from_mime(mime, "selection", "chrome.exe", "No text")
    assert source["format"] == "markdown" and source["kind"] == "selection" and source["origin"] == "chrome.exe" and source["image"] is None
    text = source["text"]
    assert "# Report" in text and "- first" in text and "|A|B|" in text and "[the page](https://example.com/page)" in text
    assert "![" not in text


@pytest.mark.skipif(os.environ.get("QT_QPA_PLATFORM") == "offscreen", reason="the offscreen platform has no font weights")
def test_html_emphasis_survives_on_windows(app):
    mime = QMimeData()
    mime.setHtml("<p>Some <b>bold</b> text</p>")
    assert "**bold**" in source_from_mime(mime, "selection", "chrome.exe", "No text")["text"]


def test_plain_text_stays_plain(app):
    mime = QMimeData()
    mime.setText("2 * 3 # not a heading _x_")
    assert source_from_mime(mime, "clipboard", "Clipboard", "No text") == {
        "kind": "clipboard", "format": "plain", "text": "2 * 3 # not a heading _x_", "image": None, "origin": "Clipboard"}


def test_image_is_scaled_to_png(app):
    image = QImage(4000, 1000, QImage.Format_RGB32)
    image.fill(QColor("#205080"))
    mime = QMimeData()
    mime.setImageData(image)
    source = source_from_mime(mime, "clipboard", "Clipboard", "No text")
    assert source["format"] == "image" and source["text"] == ""
    png = QImage.fromData(source["image"], "PNG")
    assert (png.width(), png.height()) == (2000, 500)


def test_large_noisy_image_stays_under_the_byte_cap(app):
    noise = os.urandom(3000 * 3000 * 4)
    image = QImage(noise, 3000, 3000, QImage.Format_ARGB32).copy()
    assert len(image_png(image)) <= 3_500_000


@pytest.mark.parametrize("files", [True, False])
def test_files_or_empty_content_fail_with_the_given_message(app, files):
    mime = QMimeData()
    if files:
        mime.setUrls([QUrl.fromLocalFile("C:/synthetic/report.pdf")])
    with pytest.raises(RuntimeError, match="The clipboard has no text or image"):
        source_from_mime(mime, "clipboard", "Clipboard", "The clipboard has no text or image")
    with pytest.raises(RuntimeError, match="nothing"):
        source_from_mime(None, "clipboard", "Clipboard", "nothing")
