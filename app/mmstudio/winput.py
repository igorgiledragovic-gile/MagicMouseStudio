"""SendInput helpers (mouse buttons, wheel, keyboard chords). All injected events carry
dwExtraInfo = MMS_TAG so our own low-level hook recognises and passes them."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

user32 = ctypes.WinDLL("user32", use_last_error=True)
MMS_TAG = 0x4D4D5354  # 'MMST'

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x0020, 0x0040
MOUSEEVENTF_XDOWN, MOUSEEVENTF_XUP = 0x0080, 0x0100
MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x0800, 0x1000
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x0001, 0x0002
XBUTTON1, XBUTTON2 = 1, 2

VK_LWIN, VK_CONTROL, VK_LEFT, VK_RIGHT, VK_TAB, VK_D = 0x5B, 0x11, 0x25, 0x27, 0x09, 0x44
VK_BROWSER_BACK, VK_BROWSER_FORWARD = 0xA6, 0xA7
_EXTENDED = {VK_LWIN, VK_LEFT, VK_RIGHT, VK_BROWSER_BACK, VK_BROWSER_FORWARD}

BTN_LEFT, BTN_RIGHT, BTN_MIDDLE = "left", "right", "middle"
_DOWN = {BTN_LEFT: MOUSEEVENTF_LEFTDOWN, BTN_RIGHT: MOUSEEVENTF_RIGHTDOWN, BTN_MIDDLE: MOUSEEVENTF_MIDDLEDOWN}
_UP = {BTN_LEFT: MOUSEEVENTF_LEFTUP, BTN_RIGHT: MOUSEEVENTF_RIGHTUP, BTN_MIDDLE: MOUSEEVENTF_MIDDLEUP}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _U)]


user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]

# ---- injector thread -------------------------------------------------------------------
# SendInput can block for a long time (or forever) when some low-level hook on the system is
# slow or dead. Injection therefore runs on its own thread: the frame reader never waits on it.
import collections   # noqa: E402
import threading     # noqa: E402
import time          # noqa: E402

_q: collections.deque = collections.deque(maxlen=256)
_q_evt = threading.Event()
_busy_since = 0.0            # monotonic time the current SendInput started, 0 = idle
_sent = 0
_thread: threading.Thread | None = None
_thread_lock = threading.Lock()


def _injector():
    global _busy_since, _sent
    while True:
        _q_evt.wait(0.5)
        _q_evt.clear()
        while _q:
            try:
                items = _q.popleft()
            except IndexError:
                break
            arr = (INPUT * len(items))(*items)
            _busy_since = time.monotonic()
            user32.SendInput(len(items), arr, ctypes.sizeof(INPUT))
            _busy_since = 0.0
            _sent += 1


def _send(items: list[INPUT]) -> None:
    global _thread
    if not items:
        return
    if _thread is None:
        with _thread_lock:
            if _thread is None:
                _thread = threading.Thread(target=_injector, name="mms-injector", daemon=True)
                _thread.start()
    _q.append(items)
    _q_evt.set()


def health() -> tuple[bool, float, int]:
    """(ok, seconds the current SendInput has been blocked, events sent)."""
    blocked = time.monotonic() - _busy_since if _busy_since else 0.0
    return blocked < 1.0, blocked, _sent


def _mouse(flags: int, data: int = 0) -> INPUT:
    i = INPUT(type=INPUT_MOUSE)
    i.u.mi = MOUSEINPUT(0, 0, data & 0xFFFFFFFF, flags, 0, MMS_TAG)
    return i


def _key(vk: int, up: bool) -> INPUT:
    i = INPUT(type=INPUT_KEYBOARD)
    fl = (KEYEVENTF_EXTENDEDKEY if vk in _EXTENDED else 0) | (KEYEVENTF_KEYUP if up else 0)
    i.u.ki = KEYBDINPUT(vk, 0, fl, 0, MMS_TAG)
    return i


def button(btn: str, down: bool) -> None:
    _send([_mouse((_DOWN if down else _UP)[btn])])


def click(btn: str) -> None:
    _send([_mouse(_DOWN[btn]), _mouse(_UP[btn])])


def wheel(delta: int, horizontal: bool = False) -> None:
    if delta:
        _send([_mouse(MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL, int(delta))])


def chord(*vks: int) -> None:
    _send([_key(v, False) for v in vks] + [_key(v, True) for v in reversed(vks)])


def browser_back() -> None:
    chord(VK_BROWSER_BACK)


def browser_forward() -> None:
    chord(VK_BROWSER_FORWARD)
