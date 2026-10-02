from PySide6.QtCore import QObject, QRect, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QCursor, QGuiApplication, QPixmap
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickImageProvider
from .clipboard import image_png
from .winapi import user32


class FrozenScreens(QQuickImageProvider):
    shots: list

    def __init__(self):
        super().__init__(QQuickImageProvider.Pixmap)
        self.shots = []

    def requestPixmap(self, id, size, requested_size):
        index = int(id.split("/")[0])
        return self.shots[index] if index < len(self.shots) else QPixmap()


class RegionPicker(QObject):
    picked = Signal(bytes)
    engine: QQmlEngine
    provider: FrozenScreens
    component: QQmlComponent
    escape: QTimer
    delay: QTimer
    areas: list
    windows: list
    serial: int

    def __init__(self, qml_file):
        super().__init__()
        self.engine = QQmlEngine()
        self.provider = FrozenScreens()
        self.engine.addImageProvider("frozen", self.provider)
        self.engine.rootContext().setContextProperty("picker", self)
        self.component = QQmlComponent(self.engine, QUrl.fromLocalFile(qml_file))
        self.escape = QTimer(self)
        self.escape.setInterval(50)
        self.escape.timeout.connect(lambda: self.cancel() if user32.GetAsyncKeyState(27) & 0x8000 else None)
        self.delay = QTimer(self)
        self.delay.setSingleShot(True)
        self.delay.setInterval(150)
        self.delay.timeout.connect(self.grab)
        self.areas, self.windows, self.serial = [], [], 0

    @Slot()
    def start(self):
        self.cancel()
        self.delay.start()

    def grab(self):
        screens = QGuiApplication.screens()
        self.areas = [screen.geometry() for screen in screens]
        self.provider.shots = [screen.grabWindow(0) for screen in screens]   # memory only, never written to disk
        self.serial += 1
        cursor = QCursor.pos()
        for index, screen in enumerate(screens):
            window = self.component.createWithInitialProperties({"index": index, "source": f"image://frozen/{index}/{self.serial}"})
            window.setScreen(screen)
            window.setGeometry(self.areas[index])
            window.show()
            if self.areas[index].contains(cursor):
                window.requestActivate()
            self.windows.append(window)
        # The foreground lock can refuse activation, and then the overlay gets no Esc key event.
        self.escape.start()

    @Slot()
    def cancel(self):
        self.delay.stop()
        self.escape.stop()
        for window in self.windows:
            window.close()
            window.deleteLater()
        self.windows, self.areas, self.provider.shots = [], [], []

    @Slot(int, float, float, float, float)
    def finish(self, index, x, y, width, height):
        shot, area = self.provider.shots[index], self.areas[index]
        self.cancel()
        if width < 12 or height < 12:
            return
        ratio = shot.width() / area.width()
        pixels = QRect(round(x * ratio), round(y * ratio), round(width * ratio), round(height * ratio)).intersected(shot.rect())
        self.picked.emit(image_png(shot.copy(pixels).toImage()))
