"""Qt Quick item that renders the controller's embedded mpv player."""

from __future__ import annotations

import ctypes
from typing import Any

import mpv
from OpenGL import GL
from PySide6.QtCore import Property, QMetaObject, QObject, Qt, Signal, Slot
from PySide6.QtGui import QOpenGLContext
from PySide6.QtOpenGL import (
    QOpenGLFramebufferObject,
    QOpenGLFramebufferObjectFormat,
)
from PySide6.QtQuick import QQuickFramebufferObject, QQuickOpenGLUtils

from .debug import get_logger

try:
    from OpenGL import GLX
except Exception:  # pragma: no cover - platform-specific import
    GLX = None


class MpvVideoItem(QQuickFramebufferObject):
    """QML-facing video surface for the embedded mpv preview."""

    controllerChanged = Signal()

    def __init__(self, parent: QQuickFramebufferObject | None = None) -> None:
        """Initialize the QML item before it is bound to a controller."""
        super().__init__(parent)
        self._controller: QObject | None = None

    def createRenderer(self) -> QQuickFramebufferObject.Renderer:
        """Create the framebuffer renderer used by Qt Quick."""
        return _MpvRenderer(self)

    def isOpaque(self) -> bool:
        """Advertise an opaque surface so Qt can compose it efficiently."""
        return True

    @Property(QObject, notify=controllerChanged)
    def controller(self) -> QObject | None:
        """Return the backend object that owns the embedded mpv player."""
        return self._controller

    @controller.setter
    def controller(self, controller: QObject | None) -> None:
        """Attach the backend and trigger a redraw when it changes."""
        if controller is self._controller:
            return
        self._controller = controller
        self.controllerChanged.emit()
        self.update()

    @Slot()
    def scheduleUpdate(self) -> None:
        """Queue a redraw from mpv's render update callback."""
        self.update()


class _MpvRenderer(QQuickFramebufferObject.Renderer):
    """OpenGL-backed renderer that bridges Qt Quick and mpv."""

    def __init__(self, item: MpvVideoItem) -> None:
        """Store the item reference and defer mpv setup until rendering starts."""
        super().__init__()
        self._log = get_logger("video_cutter.mpv_item")
        self._item = item
        self._framebuffer_object: QOpenGLFramebufferObject | None = None
        self._render_context: mpv.MpvRenderContext | None = None
        self._proc_address_callback = mpv.MpvGlGetProcAddressFn(self._get_proc_address)

    def createFramebufferObject(self, size: Any) -> QOpenGLFramebufferObject:
        """Create the FBO Qt renders into and lazily initialize mpv."""
        controller = self._item.controller
        if (
            self._render_context is None
            and controller is not None
            and hasattr(controller, "player")
        ):
            self._log.info("creating mpv render context")
            self._render_context = mpv.MpvRenderContext(
                controller.player,
                "opengl",
                opengl_init_params={"get_proc_address": self._proc_address_callback},
            )
            self._render_context.update_cb = self._request_update

        framebuffer_format = QOpenGLFramebufferObjectFormat()
        framebuffer_format.setAttachment(
            QOpenGLFramebufferObject.Attachment.CombinedDepthStencil,
        )
        # Keep the Python wrapper alive for as long as Qt uses the FBO.
        self._framebuffer_object = QOpenGLFramebufferObject(size, framebuffer_format)
        return self._framebuffer_object

    def synchronize(self, item: QQuickFramebufferObject) -> None:
        """Refresh the item reference before the next render pass."""
        self._item = item  # type: ignore[assignment]

    def render(self) -> None:
        """Ask mpv to draw the current frame into Qt's active framebuffer."""
        controller = self._item.controller
        if controller is None or not hasattr(controller, "player"):
            return

        if self._render_context is None:
            self._log.warning("render called without an mpv render context")
            return

        window = self._item.window()
        device_pixel_ratio = (
            window.effectiveDevicePixelRatio() if window is not None else 1.0
        )
        width = max(1, int(self._item.width() * device_pixel_ratio))
        height = max(1, int(self._item.height() * device_pixel_ratio))
        framebuffer = GL.glGetIntegerv(GL.GL_DRAW_FRAMEBUFFER_BINDING)
        self._render_context.update()
        self._render_context.render(
            flip_y=False,
            opengl_fbo={
                "fbo": int(framebuffer),
                "w": width,
                "h": height,
                "internal_format": 0,
            },
        )
        QQuickOpenGLUtils.resetOpenGLState()

    def _get_proc_address(self, _context: object, name: bytes) -> int:
        """Resolve OpenGL function pointers for mpv's render context."""
        decoded_name = name.decode("utf-8")
        address = None

        current_context = QOpenGLContext.currentContext()
        if current_context is not None:
            address = current_context.getProcAddress(decoded_name)

        if not address and GLX is not None and hasattr(GLX, "glXGetProcAddress"):
            address = GLX.glXGetProcAddress(name)

        if not address and current_context is None:
            self._log.warning(
                "no current OpenGL context for proc address %s",
                decoded_name,
            )
            return 0

        if address is None:
            return 0

        try:
            return int(address)
        except (TypeError, ValueError):
            return ctypes.cast(address, ctypes.c_void_p).value or 0

    def _request_update(self) -> None:
        """Bounce mpv update requests onto Qt's GUI thread."""
        QMetaObject.invokeMethod(
            self._item,
            "scheduleUpdate",
            Qt.ConnectionType.QueuedConnection,
        )

    def __del__(self) -> None:
        """Release the mpv render context when the renderer is discarded."""
        if self._render_context is not None:
            self._log.info("freeing mpv render context")
            self._render_context.free()
