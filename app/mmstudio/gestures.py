"""Optional 2-finger swipe gestures (off by default):
   left/right -> previous/next virtual desktop (Ctrl+Win+Left/Right), up -> Task View (Win+Tab).
Note: Apple's driver also scrolls with 2 fingers; that is why this is opt-in."""
from __future__ import annotations

import ctypes
import time

from . import protocol

user32 = ctypes.WinDLL("user32")
KEYEVENTF_KEYUP = 0x2
VK_LWIN, VK_CONTROL, VK_LEFT, VK_RIGHT, VK_TAB = 0x5B, 0x11, 0x25, 0x27, 0x09
EXTENDED = {VK_LEFT, VK_RIGHT, VK_LWIN}

SWIPE_DIST = 650      # surface units (x range ~2360)
SWIPE_TIME = 0.45     # s
COOLDOWN = 0.7


def _chord(*vks):
    for vk in vks:
        user32.keybd_event(vk, 0, 0x1 if vk in EXTENDED else 0, 0)
    for vk in reversed(vks):
        user32.keybd_event(vk, 0, (0x1 if vk in EXTENDED else 0) | KEYEVENTF_KEYUP, 0)


class GestureEngine:
    def __init__(self):
        self.start = None        # (t, cx, cy)
        self.last_fire = 0.0

    def feed(self, fr: protocol.TouchFrame) -> str | None:
        down = [t for t in fr.touches if t.down]
        now = time.monotonic()
        if len(down) != 2 or fr.buttons:
            self.start = None
            return None
        cx = sum(t.x for t in down) / 2
        cy = sum(t.y for t in down) / 2
        if self.start is None or now - self.start[0] > SWIPE_TIME:
            self.start = (now, cx, cy)
            return None
        if now - self.last_fire < COOLDOWN:
            return None
        dx, dy = cx - self.start[1], cy - self.start[2]
        action = None
        if abs(dx) > SWIPE_DIST and abs(dx) > 2 * abs(dy):
            action = "desktop-right" if dx < 0 else "desktop-left"
        elif -dy > SWIPE_DIST and abs(dy) > 2 * abs(dx):
            action = "task-view"
        if action:
            self.last_fire, self.start = now, None
            if action == "desktop-left":
                _chord(VK_CONTROL, VK_LWIN, VK_LEFT)
            elif action == "desktop-right":
                _chord(VK_CONTROL, VK_LWIN, VK_RIGHT)
            else:
                _chord(VK_LWIN, VK_TAB)
        return action
