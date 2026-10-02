import argparse
import multiprocessing
import os
from pathlib import Path
import sys


def main():
    multiprocessing.freeze_support()
    if "--native-host" in sys.argv:
        from .bridge import native_host
        raise SystemExit(native_host())
    os.environ["QT_QUICK_CONTROLS_STYLE"] = "Material"
    os.environ["QT_QUICK_CONTROLS_MATERIAL_VARIANT"] = "Dense"
    from PySide6.QtCore import QLockFile, QProcess, QTimer, Qt, QUrl
    from PySide6.QtGui import QAction, QIcon, QPixmap, QPainter, QColor, QCursor, QFont
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickView
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox
    from . import __version__
    from .config import data_dir
    from .controller import Controller
    from .install_registration import InstallRegistration
    from .region import RegionPicker
    from .translation import reader_size
    from .updates import Updates
    parser = argparse.ArgumentParser()
    parser.add_argument("--settings", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--smoke-pages", action="store_true")
    parser.add_argument("--screenshot")
    options = parser.parse_args()
    app = QApplication(sys.argv)
    app.setApplicationName("Desktop AI Assistant")
    app.setOrganizationName("DesktopAiAssistant")
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont("Segoe UI", 10))
    lock = QLockFile(str(data_dir() / "instance.lock"))
    if not lock.tryLock(50):
        QMessageBox.information(None, "Desktop AI Assistant", "The assistant is already running. Open Settings from its tray icon.")
        return 1
    try:
        backend = Controller(app)
    except Exception as error:
        QMessageBox.critical(None, "Desktop AI Assistant", str(error))
        return 1
    if not (options.smoke or options.smoke_pages or options.screenshot):
        backend.setupBrowser()
    qml = Path(__file__).parent / "qml"
    view = QQuickView()
    view.setFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
    view.setColor(QColor("transparent"))
    view.rootContext().setContextProperty("backend", backend)
    view.setSource(QUrl.fromLocalFile(str(qml / "Overlay.qml")))
    view.setResizeMode(QQuickView.SizeRootObjectToView)
    view.resize(720, 720)
    backend.ring_window = int(view.winId())
    settings_engine = QQmlApplicationEngine()
    qml_errors = []
    settings_engine.warnings.connect(lambda errors: qml_errors.extend(str(error) for error in errors))
    settings_engine.rootContext().setContextProperty("backend", backend)
    translator = backend.translator
    settings_engine.rootContext().setContextProperty("translator", translator)
    updates = Updates.create(app, busy=lambda: backend.busy)
    settings_engine.rootContext().setContextProperty("updates", updates)
    settings_engine.load(QUrl.fromLocalFile(str(qml / "Settings.qml")))
    settings_engine.load(QUrl.fromLocalFile(str(qml / "Reader.qml")))
    picker = RegionPicker(str(qml / "RegionPicker.qml"))
    if view.status() == QQuickView.Error or len(settings_engine.rootObjects()) != 2 or picker.component.isError():
        errors = qml_errors + [str(error) for error in view.errors() + picker.component.errors()]
        (data_dir() / "startup-error.log").write_text("\n".join(errors), "utf-8")
        backend.close()
        return 2
    settings, reader = settings_engine.rootObjects()
    updates.set_relaunch_args(lambda: ["--settings"] if settings.isVisible() else [])
    restart_requested = False
    restart_settings = False
    restart_handled = False
    session_ending = False

    def request_restart():
        nonlocal restart_requested, restart_settings
        restart_requested = True
        restart_settings = settings.isVisible()
        app.quit()

    backend.requestRestart.connect(request_restart)

    def end_session(_manager):
        nonlocal session_ending
        session_ending = True

    def install_on_quit():
        nonlocal restart_handled
        relaunch = (["--settings"] if restart_settings else []) if restart_requested else None
        # True: the update helper starts the new build, so the plain restart below is skipped.
        restart_handled = updates.quit(session_ending, relaunch)

    app.commitDataRequest.connect(end_session)
    toast = QQuickView()
    toast.setFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
    toast.setColor(QColor("transparent"))
    toast.rootContext().setContextProperty("backend", backend)
    toast.rootContext().setContextProperty("translator", translator)
    toast.setSource(QUrl.fromLocalFile(str(qml / "StatusToast.qml")))
    if toast.status() == QQuickView.Error:
        backend.close()
        return 2
    toast_timer = QTimer(app)
    toast_timer.setSingleShot(True)
    toast_timer.timeout.connect(toast.hide)
    toast.rootObject().dismissed.connect(toast.hide)

    def position_status():
        cursor = QCursor.pos()
        screen = app.screenAt(cursor) or app.primaryScreen()
        area = screen.availableGeometry()
        toast.setPosition(area.right() - toast.width() - 18, area.bottom() - toast.height() - 18)

    def show_status(error=""):
        toast.rootObject().setProperty("failed", bool(error))
        position_status()
        toast.show()
        if backend.busy or translator.state in ("reading", "translating"):
            toast_timer.stop()
        else:
            toast_timer.start(12000 if error else 7000)

    toast.heightChanged.connect(position_status)
    backend.notification.connect(lambda message: show_status() if backend.busy else None)
    backend.finished.connect(show_status)

    def show_reader():
        area = (app.screenAt(QCursor.pos()) or app.primaryScreen()).availableGeometry()
        width, height = reader_size([translator.resultHtml], bool(translator.note), area)
        if reader.isVisible():
            reader.resize(width, height)
        else:
            reader.setGeometry(area.x() + (area.width() - width) // 2, area.y() + (area.height() - height) // 2, width, height)
        reader.show()
        reader.raise_()
        reader.requestActivate()

    def show_notice(message):
        backend.set_status(message)
        show_status(message)

    translation_toast = False

    def translation_status():
        nonlocal translation_toast
        if translator.state in ("reading", "translating"):
            if not backend.busy:
                translation_toast = True
                show_status()
        elif translation_toast:
            translation_toast = False
            # A failure keeps the toast: notice has just put the error there.
            if translator.state != "failed":
                toast.hide()

    translator.changed.connect(translation_status)
    translator.opened.connect(show_reader)

    def grow_reader():
        area = (app.screenAt(reader.position()) or app.primaryScreen()).availableGeometry()
        _, height = reader_size([translator.resultHtml, translator.conversationHtml], bool(translator.note), area)
        # An answer only grows the window, so a size the user chose is never reduced.
        if height > reader.height():
            reader.resize(reader.width(), height)

    translator.answered.connect(grow_reader)
    translator.notice.connect(show_notice)
    translator.regionRequested.connect(lambda: (toast.hide(), picker.start()))
    translator.stopped.connect(picker.cancel)
    picker.picked.connect(translator.region_picked)
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#142536"))
    painter.setPen(QColor("#72e1c2"))
    painter.drawEllipse(4, 4, 56, 56)
    painter.setBrush(QColor("#72e1c2"))
    painter.drawEllipse(23, 23, 18, 18)
    painter.end()
    icon = QIcon(pixmap)
    app.setWindowIcon(icon)
    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip("Desktop AI Assistant · " + backend.config.value["hotkey"])
    menu = QMenu()
    settings_action = menu.addAction("Settings", lambda: backend.requestSettings.emit("settings"))
    menu.addAction("History", lambda: backend.requestSettings.emit("history"))
    menu.addAction("Pause / resume hotkeys", backend.togglePause)
    menu.addAction("Stop action", backend.cancel)
    menu.addAction("Restart app", backend.restartApp)
    menu.addSeparator()
    menu.addAction("Quit", app.quit)
    update_action = QAction(updates.trayText, menu)
    update_action.triggered.connect(updates.trayActivate)

    def apply_tray():
        update_action.setText(updates.trayText)
        update_action.setEnabled(updates.trayEnabled)
        update_action.setVisible(updates.trayVisible)

    updates.changed.connect(apply_tray)
    apply_tray()
    menu.insertAction(settings_action, update_action)
    menu.insertSeparator(settings_action)
    updates.balloon.connect(lambda title, message: tray.showMessage(title, message))
    updates.refused.connect(lambda message: tray.showMessage("Update", message))
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: backend.requestSettings.emit("settings") if reason == QSystemTrayIcon.DoubleClick else None)
    tray.show()
    def show_ring():
        cursor = QCursor.pos()
        screen = app.screenAt(cursor) or app.primaryScreen()
        area = screen.availableGeometry()
        view.setPosition(max(area.left(), min(cursor.x() - 360, area.right() - 719)), max(area.top(), min(cursor.y() - 360, area.bottom() - 719)))
        view.show()
    backend.requestMenu.connect(show_ring)
    backend.hideMenu.connect(view.hide)
    view.visibleChanged.connect(backend.ringVisible)
    app.aboutToQuit.connect(backend.close)
    app.aboutToQuit.connect(install_on_quit)
    if options.settings or not backend.config.path.exists() or not QSystemTrayIcon.isSystemTrayAvailable():
        settings.show()
    if options.smoke or options.smoke_pages or options.screenshot:
        backend.monitor.stop()
        backend.hover(1)
        view.show()
        settings.show()
        pages = iter(range(1, 7)) if options.smoke_pages else iter([])
        def finish_smoke():
            if options.smoke_pages:
                from PySide6.QtCore import QObject, QPointF
                button = settings.findChild(QObject, "saveButton")
                print("PAGE", settings.property("page"), "SAVE", button.isVisible(), button.mapToScene(QPointF()), flush=True)
            if options.screenshot:
                folder = Path(options.screenshot)
                folder.mkdir(parents=True, exist_ok=True)
                view.grabWindow().save(str(folder / "ring-menu-720.png"))
                page = settings.property("page")
                settings.grabWindow().save(str(folder / f"settings-page-{page}-1100.png"))
            next_page = next(pages, None)
            if next_page is not None:
                settings.setProperty("page", next_page)
                settings.setProperty("macroIndex", 0)
                QTimer.singleShot(250, finish_smoke)
                return
            print("SMOKE_OK", flush=True)
            app.quit()
        QTimer.singleShot(1800, finish_smoke)
    else:
        if getattr(sys, "frozen", False):
            InstallRegistration.sync_quietly(Path(sys.executable).parent, __version__)
        updates.start()
    result = app.exec()
    tray.hide()
    view.close()
    toast.close()
    import shiboken6
    shiboken6.delete(view)
    shiboken6.delete(toast)
    shiboken6.delete(settings_engine)
    picker.cancel()
    shiboken6.delete(picker.engine)
    lock.unlock()
    if restart_requested and not restart_handled:
        if os.environ.get("DESKTOP_AI_RUN_LOOP") == "1":
            return 75
        arguments = [] if getattr(sys, "frozen", False) else ["-m", "desktop_ai_assistant"]
        if restart_settings:
            arguments.append("--settings")
        started, _ = QProcess.startDetached(sys.executable, arguments, os.getcwd())
        if not started:
            QMessageBox.critical(None, "Desktop AI Assistant", "Restart failed. Start the application again manually.")
            return 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
