from __future__ import annotations

import locale
import sys
from pathlib import Path

from PySide6.QtQml import QQmlApplicationEngine, qmlRegisterType
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
from PySide6.QtWidgets import QApplication

from .controller import VideoEditorController
from .debug import configure_logging, env_flag, get_logger
from .mpv_item import MpvVideoItem


def main() -> int:
    configure_logging()
    log = get_logger("video_cutter.app")
    preview_enabled = not env_flag("VIDEO_CUTTER_DISABLE_PREVIEW")
    QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.OpenGL)

    app = QApplication(sys.argv)
    locale.setlocale(locale.LC_NUMERIC, "C")
    log.info("application starting preview_enabled=%s", preview_enabled)

    qmlRegisterType(MpvVideoItem, "VideoCutter", 1, 0, "MpvVideoItem")

    controller = VideoEditorController()
    app.aboutToQuit.connect(controller.shutdown)

    engine = QQmlApplicationEngine()
    engine.warnings.connect(
        lambda warnings: [
            log.error("qml warning: %s", warning.toString()) for warning in warnings
        ],
    )
    engine.rootContext().setContextProperty("previewEnabled", preview_enabled)
    engine.rootContext().setContextProperty("backend", controller)
    engine.load(str(Path(__file__).with_name("qml").joinpath("Main.qml")))

    if not engine.rootObjects():
        log.error("no root QML objects were created")
        return 1

    log.info("application initialized")
    return app.exec()
