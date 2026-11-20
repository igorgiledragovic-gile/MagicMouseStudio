"""Low-level mouse hook — thin wrapper around the native mmshook.dll (see app/native/mmshook.c).

The hook itself runs in C on its own high-priority thread, so mouse moves never wait for Python.
Python only feeds it state from the touch frames: touch(), set_click(map), config(...)."""
from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass

from . import winput

_DLL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mmshook.dll")

MAP_LEFT, MAP_RIGHT, MAP_MIDDLE = 1, 2, 4
_BIT = {winput.BTN_LEFT: MAP_LEFT, winput.BTN_RIGHT: MAP_RIGHT, winput.BTN_MIDDLE: MAP_MIDDLE}


class _STATS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_long) for n in
                ("wheel_seen", "wheel_swallowed", "click_apple", "click_other", "alive", "hook_error")]


@dataclass
class HookStats:
    wheel_seen: int
    wheel_swallowed: int
    click_apple: int
    click_other: int
    alive: bool
    error: int


def buttons_to_map(buttons: list[str]) -> int:
    m = 0
    for b in buttons:
        m |= _BIT[b]
    return m


class MouseHook:
    def __init__(self):
        self.dll = None
        self.error = 0
        try:
            self.dll = ctypes.CDLL(_DLL_PATH)
            self.dll.mms_start.restype = ctypes.c_int
            self.dll.mms_set_click.argtypes = [ctypes.c_int]
            self.dll.mms_config.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
            self.dll.mms_stats.argtypes = [ctypes.POINTER(_STATS)]
        except OSError as e:
            self.error = e.winerror or -1
            self.dll = None

    @property
    def available(self) -> bool:
        return self.dll is not None

    def start(self) -> bool:
        if not self.dll:
            return False
        ok = bool(self.dll.mms_start())
        if not ok:
            self.error = self.stats().error
        return ok

    def stop(self) -> None:
        if self.dll:
            self.dll.mms_stop()

    # ---- state from the engine (cheap, called from the frame reader thread) ----
    def touch(self) -> None:
        if self.dll:
            self.dll.mms_touch()

    def set_click(self, buttons: list[str]) -> None:
        if self.dll:
            self.dll.mms_set_click(buttons_to_map(buttons))

    def config(self, scroll_studio: bool, click_studio: bool, enabled: bool) -> None:
        if self.dll:
            self.dll.mms_config(int(scroll_studio), int(click_studio), int(enabled))

    def stats(self) -> HookStats:
        s = _STATS()
        if self.dll:
            self.dll.mms_stats(ctypes.byref(s))
        return HookStats(s.wheel_seen, s.wheel_swallowed, s.click_apple, s.click_other, bool(s.alive), s.hook_error)

    @property
    def alive(self) -> bool:
        return self.stats().alive
