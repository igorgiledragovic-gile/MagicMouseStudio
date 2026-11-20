"""User-mode gesture engine fed with raw Magic Mouse 2 touch frames.

Implements the Magic-Utilities-style feature set on top of mmsfilter's raw frames:
  * scroll engine (1/2 fingers, natural, orthogonal lock, no-horizontal, acceleration, speed,
    smooth + momentum, stop on mouse move)            -> injected wheel events
  * 1/2/3-finger tap-to-click with zones, double-tap drag
  * 1-finger flick = back/forward, 2-finger swipe = virtual desktops / Task View / Desktop View
  * physical click mapping: split, swap, left-handed, middle click (4 variants), simultaneous clicks
The low-level hook (hook.py) asks this engine whether a wheel/button event came from the Apple mouse
(correlated with the touch frames) so the other mouse is never touched.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from . import protocol, winput
from .settings import (KIND_MIDDLE, KIND_PRIMARY, KIND_SECONDARY, MIDDLE_ANY_TWO, MIDDLE_ONE_FINGER_CENTER,
                       MIDDLE_THREE, MIDDLE_WIDE_TWO, OWNER_STUDIO, SCROLL_ONE, SCROLL_ONE_OR_TWO, SCROLL_TWO,
                       Settings)

W = protocol.X_MAX - protocol.X_MIN      # surface width  (units)
L = protocol.Y_MAX - protocol.Y_MIN      # surface length (units)
TOUCH_ACTIVE_WINDOW = 0.15               # s: wheel events this close to a touch belong to the Apple mouse
CLICK_CORRELATE_WAIT = 0.035             # s: hook waits this long for the matching click frame
CLICK_CORRELATE_AGE = 0.12               # s


def fx(t: protocol.Touch) -> float:
    return t.x - protocol.X_MIN          # 0 = left edge


def fy(t: protocol.Touch) -> float:
    return t.y - protocol.Y_MIN          # 0 = front edge


@dataclass
class _Finger:
    x0: float
    y0: float
    x: float
    y: float
    max_dist: float = 0.0
    max_size: int = 0


@dataclass
class _Session:
    t0: float
    fingers: dict = field(default_factory=dict)
    max_fingers: int = 0
    clicked: bool = False
    mode: str | None = None              # None | scroll | blocked
    axis: str | None = None              # v | h | None (both)
    prev_c: tuple | None = None
    prev_ids: frozenset = frozenset()
    c0: tuple | None = None
    body_move: int = 0
    dragging: bool = False
    vel: list = field(default_factory=list)
    acc_v: float = 0.0
    acc_h: float = 0.0
    tap_area_ok: bool = True
    ignored_any: bool = False


class InputEngine:
    def __init__(self, settings: Settings, on_action=None, hook=None):
        self.s = settings
        self.hook = hook                      # native MouseHook (hook.py) or None
        self.on_action = on_action or (lambda name: None)
        self.lock = threading.Lock()
        self.session: _Session | None = None
        self.prev_buttons = 0
        self.last_touch_t = 0.0
        self.apple_click_t = 0.0
        self.click_touches: list = []
        self.click_evt = threading.Event()
        self.mapped: dict[str, list[str]] = {}      # physical button -> injected buttons
        self.block_until = 0.0
        self.last_tap1_t = -1.0
        self._momentum_stop = threading.Event()
        self._momentum_thread: threading.Thread | None = None
        self.enabled = True

    # ------------------------------------------------------------------ helpers
    def _ignored(self, t) -> bool:
        s = self.s
        x, y = fx(t), fy(t)
        if self.s.left_handed:
            x = W - x
        return x < s.ignore_side_left or (W - x) < s.ignore_side_right or (L - y) < s.ignore_bottom

    def _phys(self, kind: int) -> str:
        if kind == KIND_MIDDLE:
            return winput.BTN_MIDDLE
        swap = self.s.swap_buttons ^ self.s.left_handed
        primary = kind == KIND_PRIMARY
        return winput.BTN_LEFT if primary ^ swap else winput.BTN_RIGHT

    # ------------------------------------------------------------------ frames
    def set_enabled(self, on: bool) -> None:
        self.enabled = on
        self._push_config()

    def _push_config(self) -> None:
        if self.hook:
            # fail-safe: while SendInput is blocked on the system we could swallow the Apple wheel/clicks
            # but not re-inject them -> hand everything back to the Apple driver until it recovers
            healthy = winput.health()[0]
            self.hook.config(healthy and self.s.scroll_owner == OWNER_STUDIO,
                             healthy and self.s.click_owner == OWNER_STUDIO, self.enabled)

    def feed(self, fr: protocol.TouchFrame) -> None:
        self._push_config()
        if not self.enabled:
            return
        now = time.monotonic()
        down = [t for t in fr.touches if t.down]
        if down and self.hook:
            self.hook.touch()                 # native hook: wheel events now belong to the Apple mouse
        with self.lock:
            if fr.buttons and not self.prev_buttons:
                self.apple_click_t = now
                self.click_touches = list(down)
                self.click_evt.set()
                if self.hook:                 # tell the native hook which buttons this click becomes
                    self.hook.set_click(self._map_click(down))
            self.prev_buttons = fr.buttons
            if down:
                self.last_touch_t = now

        if not down:
            if self.session:
                self._end_session(self.session, now)
                self.session = None
            return

        ses = self.session
        if ses is None:
            self._stop_momentum()
            ses = self.session = _Session(t0=now)
            # double-tap drag: second touch shortly after a 1-finger tap
            dt = (now - self.last_tap1_t) * 1000
            if self.s.double_tap_drag and self.s.tap1 and self.s.double_tap_drag_min <= dt <= self.s.double_tap_drag_max \
                    and len(down) == 1:
                ses.dragging = True
                winput.button(winput.BTN_LEFT, True)
                self.on_action("double-tap drag")
            first = down[0]
            ses.tap_area_ok = fy(first) < self.s.tap_area_from_top

        valid = [t for t in down if not self._ignored(t)]
        if len(valid) != len(down):
            ses.ignored_any = True
        for t in down:
            f = ses.fingers.get(t.id)
            if f is None:
                ses.fingers[t.id] = _Finger(t.x, t.y, t.x, t.y, 0.0, t.size)
            else:
                f.x, f.y = t.x, t.y
                f.max_dist = max(f.max_dist, abs(t.x - f.x0) + abs(t.y - f.y0))
                f.max_size = max(f.max_size, t.size)
        ses.max_fingers = max(ses.max_fingers, len(valid))
        ses.body_move += abs(fr.dx) + abs(fr.dy)
        if fr.buttons:
            ses.clicked = True
        if ses.clicked or ses.dragging or not valid:
            ses.prev_c = None
            return

        n = len(valid)
        cx = sum(t.x for t in valid) / n
        cy = sum(t.y for t in valid) / n
        ids = frozenset(t.id for t in valid)
        if ses.prev_c is None or ids != ses.prev_ids:
            ses.prev_c, ses.prev_ids, ses.c0 = (cx, cy), ids, (cx, cy)
            return
        dvx, dvy = cx - ses.prev_c[0], cy - ses.prev_c[1]
        ses.prev_c = (cx, cy)
        tx, ty = cx - ses.c0[0], cy - ses.c0[1]
        if ses.mode == "blocked" or now < self.block_until:
            return

        # ---- swipes (decided before the scroll dead zone is crossed) ----
        if ses.mode is None:
            act = self._swipe(n, dvx, dvy, tx, ty)
            if act:
                ses.mode = "blocked"
                block = self.s.swipe_navi_block if act.startswith("nav") else self.s.swipe_other_block
                self.block_until = now + block / 1000
                self.on_action(act)
                return

        # ---- scroll ----
        s = self.s
        if not (s.scrolling and s.scroll_owner == OWNER_STUDIO):
            return
        allowed = (n == 1 and s.scroll_fingers in (SCROLL_ONE, SCROLL_ONE_OR_TWO)) or \
                  (n == 2 and s.scroll_fingers in (SCROLL_ONE_OR_TWO, SCROLL_TWO))
        if not allowed:
            return
        if ses.mode is None:
            if abs(ty) > s.scroll_v_offset or (not s.scroll_no_horizontal and abs(tx) > s.scroll_h_offset):
                ses.mode = "scroll"
                if s.scroll_no_horizontal:
                    ses.axis = "v"
                elif s.scroll_orthogonal_only:
                    ses.axis = "v" if abs(ty) >= abs(tx) else "h"
            else:
                return
        if s.scroll_stop_on_mouse_move and abs(fr.dx) + abs(fr.dy) > s.stop_scroll_move_offset * 8:
            ses.mode = "blocked"
            return
        self._scroll(ses, dvx, dvy)

    def _swipe(self, n, dvx, dvy, tx, ty) -> str | None:
        s = self.s
        horiz = abs(dvx) > 2 * abs(dvy) and abs(tx) > 250
        vert = abs(dvy) > 2 * abs(dvx) and abs(ty) > 250
        if n == 1 and horiz and abs(dvx) >= s.swipe_h_offset:
            left = dvx < 0
            if (left and s.swipe_navigate_left) or (not left and s.swipe_navigate_right):
                back = left ^ (not s.swap_navigate)  # swap off: flick right = back (macOS); swap on: flick left = back
                (winput.browser_back if back else winput.browser_forward)()
                return "nav-back" if back else "nav-forward"
        if n == 2:
            if horiz and abs(dvx) >= s.swipe2_h_offset:
                left = dvx < 0
                if (left and s.swipe2_left) or (not left and s.swipe2_right):
                    nxt = left ^ s.swap_desktop_direction   # fingers to the left -> next desktop (macOS feel)
                    winput.chord(winput.VK_CONTROL, winput.VK_LWIN, winput.VK_RIGHT if nxt else winput.VK_LEFT)
                    return "desktop-next" if nxt else "desktop-prev"
            if vert and abs(dvy) >= s.swipe2_v_offset:
                up = dvy < 0                      # towards the front edge
                if up and s.swipe2_up:
                    winput.chord(winput.VK_LWIN, winput.VK_TAB)
                    return "task-view"
                if not up and s.swipe2_down:
                    winput.chord(winput.VK_LWIN, winput.VK_D)
                    return "desktop-view"
        return None

    # ------------------------------------------------------------------ scrolling
    def _gain(self, v: float) -> float:
        s = self.s
        # exponential around the MU default 60: 1 -> x0.13, 60 -> x1, 100 -> x4
        k = 0.55 * 2.0 ** ((s.scroll_speed - 60) / 20.0)
        if s.scroll_accelerated:
            k *= 1.0 + min(max((abs(v) - 8.0) / 25.0, 0.0), 4.0)
        return k

    def _scroll(self, ses: _Session, dvx: float, dvy: float) -> None:
        s = self.s
        # MU semantics (confirmed by the user): inverse ON = like a wheel: finger towards the palm
        # (y grows) scrolls DOWN (negative wheel); OFF = "natural" (content follows the finger).
        if ses.axis in (None, "v"):
            d = dvy * self._gain(dvy) * (-1 if s.scroll_inverse_v else 1)
            ses.acc_v += d
            ses.vel.append(("v", d))
        if ses.axis in (None, "h") and not s.scroll_no_horizontal:
            d = -dvx * self._gain(dvx) * (-1 if s.scroll_inverse_h else 1)
            ses.acc_h += d
            ses.vel.append(("h", d))
        ses.vel = ses.vel[-8:]
        self._flush(ses)

    def _flush(self, ses: _Session) -> None:
        step = max(1, self.s.scroll_step_factor)
        for attr, horiz in (("acc_v", False), ("acc_h", True)):
            acc = getattr(ses, attr)
            if self.s.scroll_smooth:
                if abs(acc) >= 6:
                    winput.wheel(int(acc), horiz)
                    setattr(ses, attr, acc - int(acc))
            else:
                n = int(acc / step)
                if n:
                    winput.wheel(n * step, horiz)
                    setattr(ses, attr, acc - n * step)

    def _start_momentum(self, ses: _Session) -> None:
        vs = [d for a, d in ses.vel if a == "v"][-5:]
        hs = [d for a, d in ses.vel if a == "h"][-5:]
        v = sum(vs) / len(vs) if vs else 0.0
        h = sum(hs) / len(hs) if hs else 0.0
        if abs(v) < 4 and abs(h) < 4:
            return
        self._momentum_stop.clear()

        def run():
            vv, hh, av, ah = v, h, 0.0, 0.0
            while not self._momentum_stop.wait(0.011):
                vv *= 0.94
                hh *= 0.94
                av += vv
                ah += hh
                if abs(av) >= 1:
                    winput.wheel(int(av)); av -= int(av)
                if abs(ah) >= 1:
                    winput.wheel(int(ah), True); ah -= int(ah)
                if abs(vv) < 0.8 and abs(hh) < 0.8:
                    break

        self._momentum_thread = threading.Thread(target=run, name="mms-momentum", daemon=True)
        self._momentum_thread.start()

    def _stop_momentum(self) -> None:
        self._momentum_stop.set()

    # ------------------------------------------------------------------ taps
    def _end_session(self, ses: _Session, now: float) -> None:
        s = self.s
        if ses.dragging:
            winput.button(winput.BTN_LEFT, False)
            return
        if ses.mode == "scroll":
            if s.scroll_smooth and s.scroll_momentum:
                self._start_momentum(ses)
            return
        if ses.mode or ses.clicked:
            return
        dur = (now - ses.t0) * 1000
        n = ses.max_fingers
        if n == 0 or dur > s.tap_delay or ses.body_move > 40:
            return
        if any(f.max_dist > s.tap_offset_allowed for f in ses.fingers.values()):
            return
        if max((f.max_size for f in ses.fingers.values()), default=0) < s.tap_sense:
            return
        btn = None
        if n == 1 and s.tap1:
            if (s.tap1_use_tap_area and not ses.tap_area_ok) or (s.tap1_filter_ignore_areas and ses.ignored_any):
                return
            f = next(iter(ses.fingers.values()))
            x = f.x0 - protocol.X_MIN
            if s.left_handed:
                x = W - x
            if s.tap1_middle and s.middle1_start <= x <= s.middle1_end:
                btn = self._phys(s.tap1_middle_kind)
            elif x < W * s.button_split / 100:
                btn = self._phys(s.tap1_left_kind) if s.tap1_left else None
            else:
                btn = self._phys(s.tap1_right_kind) if s.tap1_right else None
            if btn:
                self.last_tap1_t = now
        elif n == 2 and s.tap2:
            if (s.tap2_use_tap_area and not ses.tap_area_ok) or (s.tap2_filter_ignore_areas and ses.ignored_any):
                return
            btn = self._phys(s.tap2_kind)
        elif n == 3 and s.tap3:
            if (s.tap3_use_tap_area and not ses.tap_area_ok) or (s.tap3_filter_ignore_areas and ses.ignored_any):
                return
            btn = self._phys(s.tap3_kind)
        if btn:
            winput.click(btn)
            self.on_action(f"tap {n} → {btn}")

    # ------------------------------------------------------------------ click mapping (used by the native hook)
    def _map_click(self, touches: list) -> list[str]:
        s = self.s
        if s.tap1 and s.tap1_ignore_real_click:
            return []
        valid = [t for t in touches if not self._ignored(t)] or touches
        n = len(valid)
        xs = sorted((W - fx(t)) if s.left_handed else fx(t) for t in valid)
        if s.middle_click:
            k = s.middle_click_kind
            if (k == MIDDLE_ONE_FINGER_CENTER and n == 1 and s.middle1_start <= xs[0] <= s.middle1_end) or \
               (k == MIDDLE_ANY_TWO and n == 2) or \
               (k == MIDDLE_WIDE_TWO and n == 2 and xs[-1] - xs[0] >= s.middle2_min_distance) or \
               (k == MIDDLE_THREE and n >= 3):
                return [winput.BTN_MIDDLE]
        split = W * s.button_split / 100
        if not valid:
            return [self._phys(KIND_PRIMARY)]
        if s.simultaneous_clicks and xs[0] < split <= xs[-1]:
            return [self._phys(KIND_PRIMARY), self._phys(KIND_SECONDARY)]
        front = min(valid, key=fy)            # the finger nearest the front edge does the clicking
        x = (W - fx(front)) if s.left_handed else fx(front)
        return [self._phys(KIND_PRIMARY if x < split else KIND_SECONDARY)]
