"""Windows desktop control through ctypes only (no extra packages): media keys, key presses, window focus.

Everything here is Windows-only, but the module imports fine anywhere so other code can reference it.
"""
import ctypes
import platform
import time
from ctypes import wintypes

IS_WIN = platform.system() == "Windows"

VK = {
    "ctrl": 0x11, "shift": 0x10, "alt": 0x12, "enter": 0x0D, "space": 0x20, "tab": 0x09, "esc": 0x1B,
    "home": 0x24, "left": 0x25, "right": 0x27,
    "play_pause": 0xB3, "next": 0xB0, "prev": 0xB1, "vol_up": 0xAF, "vol_down": 0xAE, "vol_mute": 0xAD,
}
for _c in "abcdefghijklmnopqrstuvwxyz":
    VK[_c] = ord(_c.upper())
for _d in "0123456789":
    VK[_d] = ord(_d)
# The rest of the keyboard, for computer control (screen_windows.py).
VK.update({"backspace": 0x08, "delete": 0x2E, "insert": 0x2D, "up": 0x26, "down": 0x28, "pageup": 0x21,
           "pagedown": 0x22, "end": 0x23, "win": 0x5B, "escape": 0x1B, "capslock": 0x14,
           ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF, "`": 0xC0, "[": 0xDB, "\\": 0xDC,
           "]": 0xDD, "'": 0xDE})
VK.update({f"f{i}": 0x6F + i for i in range(1, 13)})
_EXTENDED = {VK["play_pause"], VK["next"], VK["prev"], VK["vol_up"], VK["vol_down"], VK["vol_mute"], VK["home"],
             VK["left"], VK["right"], VK["up"], VK["down"], VK["delete"], VK["insert"], VK["pageup"],
             VK["pagedown"], VK["end"], VK["win"]}
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x1, 0x2, 0x4
SW_RESTORE = 9

# Titles of browser windows end with the browser's name; the tab title is the part before it.
BROWSER_SUFFIXES = ("Google Chrome", "Microsoft Edge", "Brave", "Mozilla Firefox", "Opera", "Vivaldi")


def _need_windows() -> None:
    if not IS_WIN:
        raise RuntimeError("This action only works on Windows.")


# ---------- keyboard ----------
class InputRefused(OSError):
    """Windows didn't take the key presses or clicks: the screen is locked, or the window in front runs as
    administrator while Jarvis doesn't (Windows then protects it from other programs' input)."""


def _send(events: list, strict: bool = False) -> None:
    """Hand input events to Windows. strict: raise InputRefused if Windows didn't take them all (computer control
    must know; the older voice commands carry on as they always did)."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    array = (_INPUT * len(events))(*events)
    sent = user32.SendInput(len(events), array, ctypes.sizeof(_INPUT))
    if strict and sent != len(events):
        raise InputRefused(f"Windows took {sent} of {len(events)} input events (error {ctypes.get_last_error()}).")


def _key_event(vk: int, up: bool, strict: bool = False) -> None:
    flags = (KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED else 0) | (KEYEVENTF_KEYUP if up else 0)
    _send([_INPUT(type=1, ki=_KEYBDINPUT(vk, 0, flags, 0, 0))], strict)


def press(*names: str, strict: bool = False) -> None:
    """Press keys together, e.g. press("ctrl", "l") or press("space")."""
    _need_windows()
    codes = [VK[n] for n in names]
    try:
        for code in codes:
            _key_event(code, False, strict)
    finally:
        for code in reversed(codes):   # always let go, so no key is left held down
            _key_event(code, True)
    time.sleep(0.03)


def media_key(name: str) -> None:
    """name: play_pause, next, prev, vol_up, vol_down, vol_mute. Works for whatever app owns the media session."""
    press(name)


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


TYPE_CHUNK, TYPE_PAUSE = 1, 0.015


def type_text(text: str, strict: bool = False) -> None:
    """Type text into the focused window, any language (sends Unicode characters, not key codes)."""
    _need_windows()
    # One character at a time with a breath in between: Windows 11's Notepad drops or repeats characters when they
    # come faster (measured 2026-10-22: a whole string in one batch came out as "jumps vver םםםם...", and so did
    # 2 every 12 ms once Hebrew was in the text; 1 every 15 ms arrived intact, ~60 a second; a classic text box
    # takes any pace).
    for start in range(0, len(text), TYPE_CHUNK):
        events = []
        for ch in text[start:start + TYPE_CHUNK]:
            units = ch.encode("utf-16-le")
            for i in range(0, len(units), 2):
                unit = units[i] | (units[i + 1] << 8)
                for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
                    events.append(_INPUT(type=1, ki=_KEYBDINPUT(0, unit, flags, 0, 0)))
        if events:
            _send(events, strict)
        time.sleep(TYPE_PAUSE)
    time.sleep(0.05)


CF_UNICODETEXT, GMEM_MOVEABLE = 13, 0x0002
_clip_dlls = None


def _clipboard_api():
    global _clip_dlls
    if _clip_dlls is None:
        user32, kernel32 = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
        user32.OpenClipboard.argtypes, user32.OpenClipboard.restype = [wintypes.HWND], wintypes.BOOL
        user32.GetClipboardData.argtypes, user32.GetClipboardData.restype = [wintypes.UINT], wintypes.HANDLE
        user32.SetClipboardData.argtypes, user32.SetClipboardData.restype = [wintypes.UINT, wintypes.HANDLE], \
            wintypes.HANDLE
        user32.EnumClipboardFormats.argtypes, user32.EnumClipboardFormats.restype = [wintypes.UINT], wintypes.UINT
        user32.RegisterClipboardFormatW.argtypes, user32.RegisterClipboardFormatW.restype = [wintypes.LPCWSTR], \
            wintypes.UINT
        kernel32.GlobalAlloc.argtypes, kernel32.GlobalAlloc.restype = [wintypes.UINT, ctypes.c_size_t], wintypes.HANDLE
        kernel32.GlobalLock.argtypes, kernel32.GlobalLock.restype = [wintypes.HANDLE], ctypes.c_void_p
        kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = ([wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD] +
                                           [ctypes.c_int] * 4 +
                                           [wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID])
        _clip_dlls = (user32, kernel32)
    return _clip_dlls


_clip_owner = None


def _open_clipboard(user32) -> bool:
    # The clipboard needs an owner window: opened with none, Windows quietly refuses what is put on it. A hidden
    # message-only window ("STATIC", parent HWND_MESSAGE) is enough.
    global _clip_owner
    if not _clip_owner:
        _clip_owner = user32.CreateWindowExW(0, "STATIC", "Jarvis clipboard", 0, 0, 0, 0, 0, wintypes.HWND(-3),
                                             None, None, None)
    for _ in range(15):   # another app may hold it for a moment
        if user32.OpenClipboard(_clip_owner):
            return True
        time.sleep(0.02)
    return False


def _put_clipboard_text(user32, kernel32, text: str) -> None:
    """Replace what's on the (open) clipboard with this text, kept out of clipboard history and cloud sync."""
    user32.EmptyClipboard()
    for fmt, data in ((CF_UNICODETEXT, (text + "\0").encode("utf-16-le")),
                      (user32.RegisterClipboardFormatW("ExcludeClipboardContentFromMonitorProcessing"), b"\0\0\0\0"),
                      (user32.RegisterClipboardFormatW("CanIncludeInClipboardHistory"), b"\0\0\0\0"),
                      (user32.RegisterClipboardFormatW("CanUploadToCloudClipboard"), b"\0\0\0\0")):
        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        pointer = kernel32.GlobalLock(handle)
        ctypes.memmove(pointer, data, len(data))
        kernel32.GlobalUnlock(handle)
        user32.SetClipboardData(fmt, handle)


def paste_text(text: str) -> bool:
    """Put text into the focused field in one go, through the clipboard and Ctrl+V: exact and instant in every app,
    where key-by-key typing gets garbled by slow ones. The user's clipboard text is put back afterwards. False (and
    nothing done) when the clipboard holds something other than text (a picture, files), which must not be lost."""
    _need_windows()
    user32, kernel32 = _clipboard_api()
    if not _open_clipboard(user32):
        return False
    try:
        formats, fmt = set(), 0
        while True:
            fmt = user32.EnumClipboardFormats(fmt)
            if not fmt:
                break
            formats.add(fmt)
        if formats and CF_UNICODETEXT not in formats:
            return False
        previous = None
        if CF_UNICODETEXT in formats:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            pointer = kernel32.GlobalLock(handle) if handle else None
            if pointer:
                previous = ctypes.wstring_at(pointer)
                kernel32.GlobalUnlock(handle)
        _put_clipboard_text(user32, kernel32, text)
    finally:
        user32.CloseClipboard()
    press("ctrl", "v", strict=True)
    # shortcut: the app reads the clipboard while handling Ctrl+V; a second covers even a busy one, but an app slower
    # than that would paste the restored text. Upgrade to restoring on the next step if that's ever seen.
    time.sleep(1.0)
    if _open_clipboard(user32):
        try:
            if previous is None:
                user32.EmptyClipboard()
            else:
                _put_clipboard_text(user32, kernel32, previous)
        finally:
            user32.CloseClipboard()
    return True


# ---------- mouse (computer control) ----------
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_WHEEL = 0x0800


def make_dpi_aware() -> None:
    """Use real pixels everywhere, so positions read from the screen and positions clicked are the same numbers."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def _mouse(flags: int, data: int = 0) -> None:
    _send([_INPUT(type=0, mi=_MOUSEINPUT(0, 0, data, flags, 0, 0))], strict=True)   # only computer control clicks


def click(x: int, y: int, button: str = "left", double: bool = False) -> None:
    _need_windows()
    ctypes.windll.user32.SetCursorPos(int(x), int(y))
    time.sleep(0.05)
    down, up = (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP) if button == "right" else \
               (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP)
    for _ in range(2 if double else 1):
        _mouse(down)
        _mouse(up)
        time.sleep(0.06)


MOUSEEVENTF_MOVE, MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_VIRTUALDESK = 0x0001, 0x8000, 0x4000


def _move_to(x: int, y: int) -> None:
    # A real move event (not just SetCursorPos): drag-and-drop in Explorer and the browsers only follows those.
    user32 = ctypes.windll.user32
    left, top = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    width, height = max(1, user32.GetSystemMetrics(78) - 1), max(1, user32.GetSystemMetrics(79) - 1)
    dx, dy = round((x - left) * 65535 / width), round((y - top) * 65535 / height)
    _send([_INPUT(type=0, mi=_MOUSEINPUT(dx, dy, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
                                         0, 0))], strict=True)


def drag(x1: int, y1: int, x2: int, y2: int) -> None:
    """Press at one point, move there in small steps, let go at the other (files, sliders, selecting text)."""
    _need_windows()
    _move_to(x1, y1)
    time.sleep(0.05)
    _mouse(MOUSEEVENTF_LEFTDOWN)
    time.sleep(0.08)
    steps = 12
    for i in range(1, steps + 1):
        _move_to(x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps)
        time.sleep(0.02)
    time.sleep(0.08)
    _mouse(MOUSEEVENTF_LEFTUP)


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


_gdi_dlls = None


def _gdi():
    # Own handles to the DLLs, with 64-bit handle types: the shared ctypes.windll ones get other prototypes from
    # uiautomation, and an untyped handle overflows.
    global _gdi_dlls
    if _gdi_dlls is None:
        user32, gdi32 = ctypes.WinDLL("user32"), ctypes.WinDLL("gdi32")
        HDC, HGDI = wintypes.HDC, wintypes.HGDIOBJ
        user32.GetDC.restype, user32.GetDC.argtypes = HDC, [wintypes.HWND]
        user32.ReleaseDC.argtypes = [wintypes.HWND, HDC]
        gdi32.CreateCompatibleDC.restype, gdi32.CreateCompatibleDC.argtypes = HDC, [HDC]
        gdi32.CreateDIBSection.restype = HGDI
        gdi32.CreateDIBSection.argtypes = [HDC, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                                           wintypes.HANDLE, wintypes.DWORD]
        gdi32.SelectObject.restype, gdi32.SelectObject.argtypes = HGDI, [HDC, HGDI]
        gdi32.SetStretchBltMode.argtypes = [HDC, ctypes.c_int]
        gdi32.StretchBlt.argtypes = [HDC] + [ctypes.c_int] * 4 + [HDC] + [ctypes.c_int] * 4 + [wintypes.DWORD]
        gdi32.DeleteObject.argtypes, gdi32.DeleteDC.argtypes = [HGDI], [HDC]
        _gdi_dlls = (user32, gdi32)
    return _gdi_dlls


def screen_sample(width: int = 192, height: int = 80) -> bytes:
    """The primary screen shrunk to a tiny grey picture (one byte per pixel), in a few dozen milliseconds: enough to
    tell whether the screen is still changing, far cheaper than a real screenshot."""
    _need_windows()
    user32, gdi32 = _gdi()
    screen_dc = user32.GetDC(None)
    memory_dc = gdi32.CreateCompatibleDC(screen_dc)
    header = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), width, -height, 1, 32, 0, 0, 0, 0, 0, 0)
    bits = ctypes.c_void_p()
    bitmap = gdi32.CreateDIBSection(screen_dc, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
    try:
        old = gdi32.SelectObject(memory_dc, bitmap)
        gdi32.SetStretchBltMode(memory_dc, 3)   # COLORONCOLOR: point samples, so a blinking caret rarely shows
        gdi32.StretchBlt(memory_dc, 0, 0, width, height, screen_dc, 0, 0, user32.GetSystemMetrics(0),
                         user32.GetSystemMetrics(1), 0x00CC0020)
        raw = ctypes.string_at(bits, width * height * 4)
        gdi32.SelectObject(memory_dc, old)
    finally:
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(None, screen_dc)
    return raw[1::4]   # the green channel of each BGRX pixel is grey enough to compare


def scroll(amount: int, x: int = None, y: int = None) -> None:
    """amount: positive scrolls up, negative down (in notches)."""
    _need_windows()
    if x is not None and y is not None:
        ctypes.windll.user32.SetCursorPos(int(x), int(y))
    _mouse(MOUSEEVENTF_WHEEL, ctypes.c_uint32(int(amount) * 120).value)


def cursor_position() -> tuple:
    _need_windows()
    point = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return (point.x, point.y)


_kernel32 = None


def _process_api():
    """kernel32 with exact signatures (set up once): a process handle is pointer-sized, and ctypes' default int
    return type would cut it short on 64-bit Windows."""
    global _kernel32
    if _kernel32 is None:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = wintypes.HANDLE
        k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                 ctypes.POINTER(wintypes.DWORD))
        k.CloseHandle.argtypes = (wintypes.HANDLE,)
        _kernel32 = k
    return _kernel32


def window_process_path(hwnd: int) -> str:
    """The full path of the program a window belongs to, e.g. "C:\\Program Files\\Blender Foundation\\Blender 4.5\\
    blender.exe", or "" if it can't be read (another user's or an elevated process)."""
    _need_windows()
    kernel32 = _process_api()
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    handle = kernel32.OpenProcess(0x1000, False, pid.value)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value.replace("/", "\\")
    finally:
        kernel32.CloseHandle(handle)
    return ""


def window_process_name(hwnd: int) -> str:
    """The program a window belongs to, e.g. "chrome.exe" (lower case), or "" if it can't be read."""
    return window_process_path(hwnd).rsplit("\\", 1)[-1].lower()


def foreground_window() -> int:
    _need_windows()
    return ctypes.windll.user32.GetForegroundWindow()


def window_title(hwnd: int) -> str:
    _need_windows()
    user32 = ctypes.windll.user32
    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


# ---------- windows ----------
def list_windows() -> list:
    """Visible top-level windows with a title, front-most first: [(hwnd, title)]."""
    _need_windows()
    user32 = ctypes.windll.user32
    found = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                found.append((hwnd, buffer.value))
        return True

    user32.EnumWindows(callback_type(callback), 0)
    return found


def is_browser_title(title: str) -> bool:
    return any(title.endswith(suffix) for suffix in BROWSER_SUFFIXES)


def find_windows(*needles: str, browsers_only: bool = True) -> list:
    """Windows whose title contains any needle (case-insensitive), front-most first."""
    lowered = [n.lower() for n in needles if n]
    return [(h, t) for h, t in list_windows()
            if (not browsers_only or is_browser_title(t)) and any(n in t.lower() for n in lowered)]


def focus(hwnd: int) -> bool:
    """Bring a window to the front. Windows blocks this for background apps unless an Alt key press comes first."""
    _need_windows()
    user32 = ctypes.windll.user32
    if user32.GetForegroundWindow() == hwnd and not user32.IsIconic(hwnd):
        return True   # already in front: the Alt tap below would switch on its menu keys and eat the next shortcut
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    _key_event(VK["alt"], False)
    _key_event(VK["alt"], True)
    ok = bool(user32.SetForegroundWindow(hwnd))
    time.sleep(0.25)
    return ok


WM_CLOSE = 0x0010


def close_window(hwnd: int) -> bool:
    """Ask a window to close, exactly like clicking its X: the app can still ask to save first. Not a kill."""
    _need_windows()
    return bool(ctypes.windll.user32.PostMessageW(wintypes.HWND(hwnd), WM_CLOSE, 0, 0))


def window_exists(hwnd: int) -> bool:
    _need_windows()
    return bool(ctypes.windll.user32.IsWindow(wintypes.HWND(hwnd))) and \
        bool(ctypes.windll.user32.IsWindowVisible(wintypes.HWND(hwnd)))


def process_running(image_name: str) -> bool:
    """True if a process with this executable name is running (uses tasklist, which ships with Windows)."""
    import subprocess
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/NH"], capture_output=True,
                             text=True, timeout=8, creationflags=0x08000000).stdout
    except (subprocess.SubprocessError, OSError):
        return False
    return image_name.lower() in out.lower()
