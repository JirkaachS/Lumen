"""
Extract an application's icon from its executable (Windows) as a PIL image.

Used by the process explorer so each running app shows its real icon. Falls
back to ``None`` on any failure, in which case the UI shows a letter badge.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import POINTER, byref, c_int, c_uint, c_void_p

from PIL import Image

_CACHE: dict[str, "Image.Image | None"] = {}


def extract_icon(path: str, size: int = 32):
    """Return a PIL RGBA image of the exe's icon, or None."""
    if not path or not sys.platform.startswith("win"):
        return None
    key = f"{path}|{size}"
    if key in _CACHE:
        img = _CACHE[key]
        return img.copy() if img else None

    img = None
    try:
        img = _extract(path, size)
    except Exception:
        img = None
    _CACHE[key] = img
    return img.copy() if img else None


def _extract(path: str, size: int):
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    shell32 = ctypes.windll.shell32

    shell32.ExtractIconExW.argtypes = [
        ctypes.c_wchar_p, c_int, POINTER(c_void_p), POINTER(c_void_p), c_uint]
    shell32.ExtractIconExW.restype = c_uint
    user32.DestroyIcon.argtypes = [c_void_p]

    large = (c_void_p * 1)()
    small = (c_void_p * 1)()
    shell32.ExtractIconExW(path, 0, large, small, 1)
    hicon = large[0] or small[0]
    if not hicon:
        return None
    try:
        return _hicon_to_image(hicon, size, user32, gdi32)
    finally:
        if large[0]:
            user32.DestroyIcon(large[0])
        if small[0]:
            user32.DestroyIcon(small[0])


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", c_uint), ("biWidth", c_int), ("biHeight", c_int),
        ("biPlanes", ctypes.c_ushort), ("biBitCount", ctypes.c_ushort),
        ("biCompression", c_uint), ("biSizeImage", c_uint),
        ("biXPelsPerMeter", c_int), ("biYPelsPerMeter", c_int),
        ("biClrUsed", c_uint), ("biClrImportant", c_uint),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", c_uint * 3)]


def _hicon_to_image(hicon, size, user32, gdi32):
    user32.GetDC.restype = c_void_p
    user32.GetDC.argtypes = [c_void_p]
    user32.ReleaseDC.argtypes = [c_void_p, c_void_p]
    user32.DrawIconEx.argtypes = [
        c_void_p, c_int, c_int, c_void_p, c_int, c_int, c_uint, c_void_p, c_uint]
    gdi32.CreateCompatibleDC.restype = c_void_p
    gdi32.CreateCompatibleDC.argtypes = [c_void_p]
    gdi32.CreateDIBSection.restype = c_void_p
    gdi32.CreateDIBSection.argtypes = [
        c_void_p, c_void_p, c_uint, POINTER(c_void_p), c_void_p, c_uint]
    gdi32.SelectObject.restype = c_void_p
    gdi32.SelectObject.argtypes = [c_void_p, c_void_p]
    gdi32.DeleteObject.argtypes = [c_void_p]
    gdi32.DeleteDC.argtypes = [c_void_p]

    DIB_RGB_COLORS = 0
    DI_NORMAL = 0x0003

    bmi = _BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = size
    bmi.bmiHeader.biHeight = -size  # top-down
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0  # BI_RGB

    hdc = user32.GetDC(None)
    memdc = gdi32.CreateCompatibleDC(hdc)
    bits = c_void_p()
    hbmp = gdi32.CreateDIBSection(memdc, byref(bmi), DIB_RGB_COLORS, byref(bits), None, 0)
    if not hbmp or not bits:
        user32.ReleaseDC(None, hdc)
        gdi32.DeleteDC(memdc)
        return None
    old = gdi32.SelectObject(memdc, hbmp)
    try:
        user32.DrawIconEx(memdc, 0, 0, hicon, size, size, 0, None, DI_NORMAL)
        buf = (ctypes.c_ubyte * (size * size * 4)).from_address(bits.value)
        raw = bytes(buf)
        img = Image.frombuffer("RGBA", (size, size), raw, "raw", "BGRA", 0, 1).copy()
        # Legacy icons with no alpha channel come back fully transparent;
        # if so, make the icon opaque so it's visible.
        if not img.getbbox() or max(img.getchannel("A").getextrema()) == 0:
            rgb = img.convert("RGB")
            img = rgb.convert("RGBA")
        return img
    finally:
        gdi32.SelectObject(memdc, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(memdc)
        user32.ReleaseDC(None, hdc)
