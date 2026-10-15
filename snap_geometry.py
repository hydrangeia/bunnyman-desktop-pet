"""Visible-sprite docking geometry and read-only Windows surface discovery."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self): return self.right-self.left

    @property
    def height(self): return self.bottom-self.top

    @property
    def center_x(self): return (self.left+self.right)/2

    @property
    def center_y(self): return (self.top+self.bottom)/2

    def translated(self,x,y):
        return Rect(self.left+x,self.top+y,self.right+x,self.bottom+y)

    def contains(self,x,y):
        return self.left<=x<=self.right and self.top<=y<=self.bottom


@dataclass(frozen=True)
class Surface:
    id: str
    rect: Rect
    kind: str = 'window'
    handle: int | None = None


@dataclass(frozen=True)
class Anchor:
    surface_id: str
    side: str
    ratio: float


def _overlap(a,b,c,d):
    return min(b,d)-max(a,c)


def position_for_anchor(anchor,surface,visible):
    """Place the visible sprite outside a window or inside a screen work area."""
    r=surface.rect
    ratio=max(0,min(1,anchor.ratio))
    if anchor.side in ('top','bottom'):
        x=r.left+ratio*r.width-visible.center_x
        if anchor.side=='top':
            y=r.top-(visible.top if surface.kind=='screen' else visible.bottom)
        else:
            y=r.bottom-(visible.bottom if surface.kind=='screen' else visible.top)
    else:
        y=r.top+ratio*r.height-visible.center_y
        if anchor.side=='left':
            x=r.left-(visible.left if surface.kind=='screen' else visible.right)
        elif anchor.side=='right':
            x=r.right-(visible.right if surface.kind=='screen' else visible.left)
        else:
            raise ValueError(f'Unknown docking side: {anchor.side}')
    if surface.kind=='screen':
        if visible.width<=r.width:
            x=max(r.left-visible.left,min(r.right-visible.right,x))
        if visible.height<=r.height:
            y=max(r.top-visible.top,min(r.bottom-visible.bottom,y))
    return (round(x),round(y))


def find_snap(position,visible,surfaces,threshold=24):
    g=visible.translated(*position)
    candidates=[]
    for order,surface in enumerate(surfaces):
        r=surface.rect
        if r.width<=0 or r.height<=0:
            continue
        inside=surface.kind=='screen'
        edges={
            'top': abs((g.top if inside else g.bottom)-r.top),
            'bottom': abs((g.bottom if inside else g.top)-r.bottom),
            'left': abs((g.left if inside else g.right)-r.left),
            'right': abs((g.right if inside else g.left)-r.right),
        }
        for side,distance in edges.items():
            horizontal=side in ('top','bottom')
            overlap=(_overlap(g.left,g.right,r.left,r.right) if horizontal
                     else _overlap(g.top,g.bottom,r.top,r.bottom))
            if distance>threshold or overlap<min(20,visible.width/3 if horizontal else visible.height/3):
                continue
            ratio=((g.center_x-r.left)/r.width if horizontal else (g.center_y-r.top)/r.height)
            anchor=Anchor(surface.id,side,max(0,min(1,ratio)))
            # The first window is foremost. Prefer a supporting top/bottom at
            # equal distance so dropping near a corner gives a stable resting spot.
            floor_rank=0 if ((inside and side=='bottom') or (not inside and side=='top')) else 1
            candidates.append((distance,floor_rank,order,anchor,surface))
    if not candidates:
        return None
    _,_,_,anchor,surface=min(candidates,key=lambda c:c[:3])
    return position_for_anchor(anchor,surface,visible),anchor


def find_support(position,visible,surfaces):
    """Find the nearest top of a window or screen floor below the sprite."""
    g=visible.translated(*position)
    candidates=[]
    for order,surface in enumerate(surfaces):
        r=surface.rect
        if r.width<=0 or r.height<=0 or not r.left<=g.center_x<=r.right:
            continue
        floor=r.bottom if surface.kind=='screen' else r.top
        if floor<g.bottom-24:
            continue
        anchor=Anchor(surface.id,'bottom' if surface.kind=='screen' else 'top',
                      max(0,min(1,(g.center_x-r.left)/r.width)))
        candidates.append((max(0,floor-g.bottom),order,surface,anchor))
    if not candidates:
        return None
    _,_,surface,anchor=min(candidates,key=lambda c:c[:2])
    return position_for_anchor(anchor,surface,visible),anchor


def native_monitor_rects():
    """Native pixel rectangles, keyed by the same DISPLAY names used by Qt."""
    if os.name!='nt':
        return {}
    import ctypes
    from ctypes import wintypes
    user=ctypes.windll.user32
    class MonitorInfo(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('monitor',wintypes.RECT),
                  ('work',wintypes.RECT),('flags',wintypes.DWORD),('device',wintypes.WCHAR*32)]
    callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HMONITOR,wintypes.HDC,
                                    ctypes.POINTER(wintypes.RECT),wintypes.LPARAM)
    user.GetMonitorInfoW.argtypes=[wintypes.HMONITOR,ctypes.POINTER(MonitorInfo)]
    result={}
    @callback_type
    def callback(handle,dc,rect,parameter):
        info=MonitorInfo();info.size=ctypes.sizeof(info)
        if user.GetMonitorInfoW(handle,ctypes.byref(info)):
            r=info.monitor
            result[info.device]=Rect(r.left,r.top,r.right,r.bottom)
        return True
    user.EnumDisplayMonitors(None,None,callback,0)
    return result


def enumerate_windows(exclude_handle=None,coordinate_mapper=None):
    """Return visible ordinary windows in front-to-back order without titles.

    coordinate_mapper is Rect -> Rect, converting native pixels to Qt logical
    coordinates. Screens are supplied separately by the UI using work areas.
    """
    if os.name!='nt':
        return []
    import ctypes
    from ctypes import wintypes
    user=ctypes.windll.user32
    dwm=ctypes.windll.dwmapi
    callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    user.IsWindowVisible.argtypes=[wintypes.HWND]
    user.IsIconic.argtypes=[wintypes.HWND]
    user.GetWindowLongW.argtypes=[wintypes.HWND,ctypes.c_int]
    user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user.GetClassNameW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    user.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    dwm.DwmGetWindowAttribute.argtypes=[wintypes.HWND,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD]
    result=[]
    @callback_type
    def callback(hwnd,parameter):
        handle=int(hwnd or 0)
        if handle==exclude_handle or not user.IsWindowVisible(hwnd) or user.IsIconic(hwnd):
            return True
        process=wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd,ctypes.byref(process))
        if process.value==os.getpid():
            return True
        style=user.GetWindowLongW(hwnd,-20)
        if style & (0x80|0x08000000):  # tool windows and non-activating overlays
            return True
        cloaked=wintypes.DWORD()
        if dwm.DwmGetWindowAttribute(hwnd,14,ctypes.byref(cloaked),ctypes.sizeof(cloaked))==0 and cloaked.value:
            return True
        name=ctypes.create_unicode_buffer(128)
        user.GetClassNameW(hwnd,name,128)
        if name.value in {'Progman','WorkerW','Shell_TrayWnd','Shell_SecondaryTrayWnd','tooltips_class32'}:
            return True
        bounds=wintypes.RECT()
        if dwm.DwmGetWindowAttribute(hwnd,9,ctypes.byref(bounds),ctypes.sizeof(bounds))!=0:
            if not user.GetWindowRect(hwnd,ctypes.byref(bounds)):
                return True
        rect=Rect(bounds.left,bounds.top,bounds.right,bounds.bottom)
        if rect.width<160 or rect.height<80:
            return True
        if coordinate_mapper:
            rect=coordinate_mapper(rect)
        # Ignore surfaces wholly hidden under an earlier, foreground window.
        if any(front.rect.left<=rect.left and front.rect.top<=rect.top
               and front.rect.right>=rect.right and front.rect.bottom>=rect.bottom for front in result):
            return True
        result.append(Surface(f'window:{handle}',rect,'window',handle))
        return True
    user.EnumWindows(callback,0)
    return result
