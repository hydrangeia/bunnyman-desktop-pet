"""Opaque, ordinary top-level window for window capture and chroma keying."""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QActionGroup, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QWidget


CAPTURE_TITLE = "兔人桌宠 · 直播采集"
BACKGROUNDS = {
    "green": ("绿幕", "#00ff00"),
    "blue": ("蓝幕", "#0000ff"),
    "magenta": ("品红幕", "#ff00ff"),
}
FRAME_CACHE_SIZE = 16


class CaptureWindow(QWidget):
    """Mirror source frames without inheriting desktop position, masks or scale.

    A regular, unowned, opaque window can be selected by both classic BitBlt
    and modern Windows capture. Transparency is supplied by the broadcaster's
    color/chroma-key filter, rather than depending on layered-window capture.
    """

    def __init__(self, canvas=(620, 616), icon: QIcon | None = None):
        super().__init__(None, Qt.WindowType.Window)
        width, height = map(int, canvas)
        if width <= 0 or height <= 0:
            raise ValueError("Capture canvas must have positive dimensions")
        self.setWindowTitle(CAPTURE_TITLE)
        self.setFixedSize(width, height)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        if icon is not None:
            self.setWindowIcon(icon)
        self.background_key = "green"
        self.frame_paths: tuple[Path, Path | None, bool] | None = None
        self._body = QPixmap()
        self._effect = QPixmap()
        self._cache: OrderedDict[tuple[Path, bool], QPixmap] = OrderedDict()

    def set_background(self, key: str) -> None:
        if key not in BACKGROUNDS:
            raise ValueError(f"Unknown capture background: {key}")
        self.background_key = key
        self.update()

    def _pixmap(self, path: Path, mirror: bool) -> QPixmap:
        key = (path, mirror)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        pixmap = QPixmap(str(path))
        if pixmap.isNull():
            raise ValueError(f"Cannot load capture frame: {path}")
        if mirror:
            pixmap = QPixmap.fromImage(pixmap.toImage().mirrored(True, False))
        self._cache[key] = pixmap
        while len(self._cache) > FRAME_CACHE_SIZE:
            self._cache.popitem(last=False)
        return pixmap

    def set_frame_paths(
        self, body: Path, effect: Path | None = None, mirror: bool = False
    ) -> None:
        paths = (Path(body), Path(effect) if effect is not None else None, bool(mirror))
        if paths == self.frame_paths:
            return
        # Decode both before publishing, so a failed image cannot leave half a frame.
        body_image = self._pixmap(paths[0], paths[2])
        effect_image = self._pixmap(paths[1], paths[2]) if paths[1] else QPixmap()
        self._body, self._effect = body_image, effect_image
        self.frame_paths = paths
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt event name
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(BACKGROUNDS[self.background_key][1]))
        for image in (self._body, self._effect):
            if not image.isNull():
                painter.drawPixmap(
                    (self.width() - image.width()) // 2,
                    (self.height() - image.height()) // 2,
                    image,
                )

    def contextMenuEvent(self, event):  # noqa: N802 - Qt event name
        menu = QMenu(self)
        colors = menu.addMenu("采集背景")
        group = QActionGroup(colors)
        group.setExclusive(True)
        for key, (label, _color) in BACKGROUNDS.items():
            action = colors.addAction(label)
            action.setCheckable(True)
            action.setChecked(key == self.background_key)
            group.addAction(action)
            action.triggered.connect(
                lambda checked=False, selected=key: self.set_background(selected)
            )
        menu.addSeparator()
        menu.addAction("关闭采集窗口", self.close)
        menu.exec(event.globalPos())

    def closeEvent(self, event):  # noqa: N802 - Qt event name
        # Closing this view leaves the desktop pet and its animation running.
        self._cache.clear()
        super().closeEvent(event)
