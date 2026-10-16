import os
from pathlib import Path
import subprocess
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from capture_window import CAPTURE_TITLE, CaptureWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def image(path, color, position):
    frame = QImage(8, 4, QImage.Format.Format_ARGB32)
    frame.fill(Qt.GlobalColor.transparent)
    frame.setPixelColor(*position, QColor(color))
    assert frame.save(str(path))
    return path


def test_capture_is_opaque_and_composites_body_effect_and_mirror(app, tmp_path):
    body = image(tmp_path / "body.png", "red", (1, 1))
    effect = image(tmp_path / "effect.png", "blue", (5, 1))
    window = CaptureWindow((8, 4))
    window.set_frame_paths(body, effect)
    frame = window.grab().toImage()
    assert frame.pixelColor(0, 0) == QColor("#00ff00")
    assert frame.pixelColor(1, 1) == QColor("red")
    assert frame.pixelColor(5, 1) == QColor("blue")
    window.set_frame_paths(body, effect, mirror=True)
    frame = window.grab().toImage()
    assert frame.pixelColor(6, 1) == QColor("red")
    assert frame.pixelColor(2, 1) == QColor("blue")
    window.set_frame_paths(body)
    frame = window.grab().toImage()
    assert frame.pixelColor(5, 1) == QColor("#00ff00")
    window.set_background("magenta")
    assert window.grab().toImage().pixelColor(0, 0) == QColor("#ff00ff")
    window.close()


def test_capture_is_a_stable_normal_window_without_a_desktop_mask(app, tmp_path):
    window = CaptureWindow((80, 40))
    assert window.windowTitle() == CAPTURE_TITLE
    assert window.windowType() == Qt.WindowType.Window
    assert not window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert not window.testAttribute(Qt.WidgetAttribute.WA_QuitOnClose)
    assert window.mask().isEmpty()
    window.resize(200, 200)
    assert (window.width(), window.height()) == (80, 40)
    window.show()
    window.close()
    window.show()
    assert window.isVisible()
    window.close()


@pytest.mark.skipif(
    os.name != "nt" or os.environ.get("BUNNY_NATIVE_CAPTURE_TESTS") != "1",
    reason="opt-in Win32 PrintWindow probe creates a brief ordinary test window",
)
def test_native_windows_can_enumerate_and_capture_the_client_area(tmp_path):
    # A new QApplication is required to test Windows instead of Qt offscreen.
    probe = tmp_path / "native_probe.py"
    probe.write_text('''
import ctypes
from ctypes import wintypes as W
from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication
from capture_window import CaptureWindow, CAPTURE_TITLE
from pathlib import Path
app=QApplication([])
path=Path(__file__).with_suffix('.png')
im=QImage(80,40,QImage.Format.Format_ARGB32);im.fill(QColor(0,0,0,0))
for x in range(20,60):
    for y in range(10,30):im.setPixelColor(x,y,QColor('red'))
im.save(str(path))
window=CaptureWindow((80,40));window.set_frame_paths(path);window.show()
result=[1]
def check():
    try:
        user=ctypes.WinDLL('user32',use_last_error=True)
        gdi=ctypes.WinDLL('gdi32',use_last_error=True)
        hwnd=int(window.winId())
        user.GetWindowLongW.argtypes=[W.HWND,ctypes.c_int]
        assert not user.GetWindowLongW(hwnd,-20)&0x80, 'Tool window is not capturable'
        assert not user.GetWindowLongW(hwnd,-20)&0x80000, 'Layered transparency leaked'
        callback=ctypes.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
        handles=[]
        @callback
        def found(h,p):handles.append(int(h));return True
        user.EnumWindows(found,0)
        assert hwnd in handles, 'Window missing from EnumWindows'
        user.GetDC.argtypes=[W.HWND];user.GetDC.restype=W.HDC
        user.ReleaseDC.argtypes=[W.HWND,W.HDC]
        user.PrintWindow.argtypes=[W.HWND,W.HDC,W.UINT];user.PrintWindow.restype=W.BOOL
        user.GetClientRect.argtypes=[W.HWND,ctypes.POINTER(W.RECT)]
        gdi.CreateCompatibleDC.argtypes=[W.HDC];gdi.CreateCompatibleDC.restype=W.HDC
        gdi.CreateCompatibleBitmap.argtypes=[W.HDC,ctypes.c_int,ctypes.c_int];gdi.CreateCompatibleBitmap.restype=W.HBITMAP
        gdi.SelectObject.argtypes=[W.HDC,W.HGDIOBJ];gdi.SelectObject.restype=W.HGDIOBJ
        gdi.GetPixel.argtypes=[W.HDC,ctypes.c_int,ctypes.c_int];gdi.GetPixel.restype=W.DWORD
        gdi.DeleteObject.argtypes=[W.HGDIOBJ];gdi.DeleteDC.argtypes=[W.HDC]
        dc=user.GetDC(hwnd);memory=gdi.CreateCompatibleDC(dc)
        bounds=W.RECT();assert user.GetClientRect(hwnd,ctypes.byref(bounds))
        width,height=bounds.right,bounds.bottom
        bitmap=gdi.CreateCompatibleBitmap(dc,width,height);old=gdi.SelectObject(memory,bitmap)
        try:
            assert user.PrintWindow(hwnd,memory,1), 'PrintWindow failed'
            assert gdi.GetPixel(memory,width//2,height//2)==0x0000ff, 'Client render was blank or contaminated'
            assert gdi.GetPixel(memory,0,0)==0x00ff00, 'Opaque background not captured'
        finally:
            gdi.SelectObject(memory,old);gdi.DeleteObject(bitmap);gdi.DeleteDC(memory);user.ReleaseDC(hwnd,dc)
        result[0]=0
        print('native EnumWindows + opaque PrintWindow capture OK',flush=True)
    except Exception:
        import traceback;traceback.print_exc()
    finally:
        window.close();app.quit()
QTimer.singleShot(250,check)
app.exec()
raise SystemExit(result[0])
''', encoding="utf-8")
    env = {**os.environ, "QT_QPA_PLATFORM": "windows", "PYTHONPATH": str(Path(__file__).parent)}
    result = subprocess.run([sys.executable, str(probe)], env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
