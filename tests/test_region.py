from pathlib import Path
import pytest
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QMouseEvent, QPainter, QPixmap
from PySide6.QtTest import QTest
import desktop_ai_assistant
from desktop_ai_assistant import region as region_module
from desktop_ai_assistant.region import RegionPicker


@pytest.fixture
def app():
    return QGuiApplication.instance() or QGuiApplication([])


@pytest.fixture
def picker(app):
    picker = RegionPicker(str(Path(desktop_ai_assistant.__file__).parent / "qml/RegionPicker.qml"))
    assert not picker.component.isError(), picker.component.errorString()
    pngs = []
    picker.picked.connect(pngs.append)
    picker.pngs = pngs
    yield picker
    picker.cancel()


def marked(width, height, mark):
    shot = QPixmap(width, height)
    shot.fill(QColor("black"))
    painter = QPainter(shot)
    painter.fillRect(mark, QColor("red"))
    painter.end()
    return shot


def single_color(png):
    image = QImage.fromData(png, "PNG")
    colors = {image.pixelColor(x, y).name() for x in (0, image.width() - 1) for y in (0, image.height() - 1)}
    return image.width(), image.height(), colors


def test_crop_uses_the_real_capture_ratio(picker):
    picker.provider.shots = [marked(3000, 2000, QRect(150, 150, 300, 150))]
    picker.areas = [QRect(0, 0, 2000, 1333)]
    picker.finish(0, 100, 100, 200, 100)
    assert [single_color(png) for png in picker.pngs] == [(300, 150, {"#ff0000"})]
    assert picker.provider.shots == [] and picker.areas == []


def test_crop_uses_screen_local_coordinates_for_a_negative_origin(picker):
    picker.provider.shots = [QPixmap(10, 10), marked(3000, 2000, QRect(150, 150, 300, 150))]
    picker.areas = [QRect(0, 0, 10, 10), QRect(-2000, -1333, 2000, 1333)]
    picker.finish(1, 100, 100, 200, 100)
    assert [single_color(png) for png in picker.pngs] == [(300, 150, {"#ff0000"})]


def test_png_long_edge_is_at_most_2000_pixels(picker):
    picker.provider.shots = [marked(3000, 2000, QRect(0, 0, 3000, 2000))]
    picker.areas = [QRect(0, 0, 2000, 1333)]
    picker.finish(0, 0, 0, 2000, 1333)
    image = QImage.fromData(picker.pngs[0], "PNG")
    assert (image.width(), image.height()) == (2000, 1333)


def fake_grab(picker, monkeypatch, app):
    screen = app.primaryScreen()
    shot = marked(screen.geometry().width(), screen.geometry().height(), QRect(10, 10, 40, 30))
    monkeypatch.setattr(screen, "grabWindow", lambda window: shot)
    monkeypatch.setattr(region_module.QGuiApplication, "screens", staticmethod(lambda: [screen, screen]))
    picker.grab()
    return list(picker.windows)


def test_small_drag_emits_nothing_and_closes_every_overlay(picker, monkeypatch, app):
    windows = fake_grab(picker, monkeypatch, app)
    assert len(windows) == 2 and all(window.isVisible() for window in windows)
    assert picker.escape.isActive()
    picker.finish(1, 10, 10, 11, 40)
    assert picker.pngs == []
    assert picker.windows == [] and not any(window.isVisible() for window in windows)
    assert not picker.escape.isActive()


def test_cancel_drops_the_frozen_images_and_closes_the_windows(picker, monkeypatch, app):
    windows = fake_grab(picker, monkeypatch, app)
    assert len(picker.provider.shots) == 2
    picker.cancel()
    assert picker.provider.shots == [] and picker.windows == []
    assert not any(window.isVisible() for window in windows)


def test_overlay_drag_emits_the_dragged_region(picker, monkeypatch, app):
    windows = fake_grab(picker, monkeypatch, app)
    window = windows[0]
    assert QTest.qWaitForWindowExposed(window)
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, QPoint(50, 40))
    QTest.mouseMove(window, QPoint(30, 20))
    QTest.mouseMove(window, QPoint(10, 10))
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, QPoint(10, 10))
    assert [single_color(png) for png in picker.pngs] == [(40, 30, {"#ff0000"})]
    assert picker.windows == []


@pytest.mark.parametrize("reverse_x,reverse_y", [(False, False), (False, True), (True, False), (True, True)])
def test_ctrl_moves_the_whole_region_then_resumes_resizing(picker, monkeypatch, app, reverse_x, reverse_y):
    screen = app.primaryScreen()
    shot = marked(400, 300, QRect(80, 70, 110, 85))
    monkeypatch.setattr(region_module.QGuiApplication, "screens", staticmethod(lambda: [screen]))
    monkeypatch.setattr(screen, "grabWindow", lambda window: shot)
    picker.grab()
    window = picker.windows[0]
    window.resize(400, 300)
    picker.areas = [QRect(0, 0, 400, 300)]
    assert QTest.qWaitForWindowExposed(window)
    band = window.findChild(QObject, "regionBand")

    def bounds():
        return tuple(band.property(key) for key in ("x", "y", "width", "height"))

    def move(x, y, ctrl=False):
        point = QPointF(x, y)
        event = QMouseEvent(QEvent.MouseMove, point, point, Qt.NoButton, Qt.LeftButton, Qt.ControlModifier if ctrl else Qt.NoModifier)
        app.sendEvent(window, event)

    start = QPoint(150 if reverse_x else 50, 130 if reverse_y else 50)
    end = QPoint(50 if reverse_x else 150, 50 if reverse_y else 130)
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
    move(end.x(), end.y())
    assert bounds() == (50, 50, 100, 80)
    move(end.x() + 30, end.y() + 20, True)
    assert bounds() == (80, 70, 100, 80)
    dx, dy = (-10 if reverse_x else 10), (-5 if reverse_y else 5)
    finish = end + QPoint(30 + dx, 20 + dy)
    move(finish.x(), finish.y())
    assert bounds() == (70 if reverse_x else 80, 65 if reverse_y else 70, 110, 85)
    QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, finish)
    image = QImage.fromData(picker.pngs[0], "PNG")
    assert (image.width(), image.height()) == (110, 85)
    assert picker.windows == []


def test_ctrl_move_clamps_at_edges_without_changing_size(picker, monkeypatch, app):
    windows = fake_grab(picker, monkeypatch, app)
    window = windows[0]
    assert QTest.qWaitForWindowExposed(window)
    band = window.findChild(QObject, "regionBand")
    QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, QPoint(50, 50))
    QTest.mouseMove(window, QPoint(150, 130))
    for point, expected in [(QPointF(-500, -500), (0, 0)),
                            (QPointF(window.width() + 500, window.height() + 500), (window.width() - 100, window.height() - 80))]:
        app.sendEvent(window, QMouseEvent(QEvent.MouseMove, point, point, Qt.NoButton, Qt.LeftButton, Qt.ControlModifier))
        assert (band.property("x"), band.property("y")) == expected
        assert (band.property("width"), band.property("height")) == (100, 80)
    picker.cancel()


@pytest.mark.parametrize("gesture", ["right", "escape"])
def test_overlay_right_click_and_escape_cancel(picker, monkeypatch, app, gesture):
    monkeypatch.setattr(region_module.QGuiApplication, "screens", staticmethod(lambda: [app.primaryScreen()]))
    monkeypatch.setattr(app.primaryScreen(), "grabWindow", lambda window: marked(64, 48, QRect(0, 0, 8, 8)))
    picker.grab()
    window = picker.windows[0]
    window.requestActivate()
    assert QTest.qWaitForWindowExposed(window)
    if gesture == "right":
        QTest.mouseClick(window, Qt.RightButton, Qt.NoModifier, QPoint(20, 20))
    elif gesture == "escape":
        assert QTest.qWaitForWindowActive(window)
        QTest.keyClick(window, Qt.Key_Escape)
    else:
        raise ValueError(gesture)
    assert picker.windows == [] and picker.provider.shots == []
    assert picker.pngs == []
