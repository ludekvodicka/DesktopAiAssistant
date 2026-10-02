import copy
import os
import threading
import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter
from desktop_ai_assistant.config import DEFAULT
from desktop_ai_assistant.providers import answer, transform, translate
from desktop_ai_assistant.text import EXPLAIN

pytestmark = pytest.mark.skipif(os.environ.get("DESKTOP_AI_LIVE_TESTS") != "1", reason="Explicit live subscription check")


@pytest.mark.parametrize("action,text,expected", [
    ("english_formal", "Dobrý den, zítra máme schůzku.", "tomorrow"),
    ("english_social", "Ahoj, koukni na https://Example.test/SomeID a dej mi vědět.", "https://Example.test/SomeID"),
    ("native", "Vcera jsme byly v praze.", "Praze"),
])
def test_live_subscription_profiles(action, text, expected):
    config = copy.deepcopy(DEFAULT)
    result = transform(config, action, text, threading.Event())
    assert expected in result


@pytest.mark.parametrize("form,text,expected", [
    ("plain", "The meeting is tomorrow. See https://example.test/Agenda for details.", "https://example.test/Agenda"),
    ("markdown", "# Shopping list\n\n- three apples\n- fresh bread", "# "),
])
def test_live_translation(form, text, expected):
    source = {"kind": "selection", "format": form, "text": text, "image": None, "origin": "test"}
    result = translate(copy.deepcopy(DEFAULT), source, threading.Event())
    assert expected in result["text"] and result["text"] != text and not result["warning"]


@pytest.fixture
def app():
    return QGuiApplication.instance() or QGuiApplication([])


def test_live_image_translation(app):
    # Text needs real fonts: the offscreen platform renders boxes, so run this on the Windows platform.
    image = QImage(900, 300, QImage.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    painter.setPen(Qt.black)
    painter.setFont(QFont("Segoe UI", 26, QFont.Bold))
    painter.drawText(40, 70, "Weekly Garden Report")
    painter.setFont(QFont("Segoe UI", 16))
    painter.drawText(40, 140, "- Water the tomatoes")
    painter.drawText(40, 200, "The weather was sunny all week.")
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    source = {"kind": "region", "format": "image", "text": "", "image": bytes(data), "origin": "test"}
    result = translate(copy.deepcopy(DEFAULT), source, threading.Event())
    assert "garden" in result["source"].lower() and result["text"].strip()


def test_live_question_and_follow_up():
    config, source, translation = copy.deepcopy(DEFAULT), "We need to circle back on this next week.", "Musíme se k tomu vrátit příští týden."
    first = answer(config, source, translation, [], EXPLAIN, threading.Event())
    second = answer(config, source, translation, [{"question": EXPLAIN, "answer": first}], "Je to formální?", threading.Event())
    assert first.strip() and second.strip() and first != second
