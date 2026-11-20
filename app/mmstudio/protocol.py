"""Apple Magic Mouse 2 wire protocol (touch + battery).

Reference: the public Linux driver drivers/hid/hid-magicmouse.c (GPL; only the
documented wire format is used here, no code copied) plus our own captures.

Touch report (ID 0x12):  [0x12, buttons, dx_lo, dx_hi, dy_lo, dy_hi, 8 bytes header-tail, N x 8-byte touch]
  length = 8 (no touch data / plain mouse mode) or 14 + 8*N
Battery report (ID 0x90): [0x90, flags, percent]
Multi-touch enable (BT, control channel, HIDP header 0x53 = SET_REPORT|Feature):
  F1 02 01  -- what Apple's applewirelessmouse.sys sends for MM2 (confirmed by RE, scratch/re/mu3164)
  F1 C8 09  -- what Linux hid-magicmouse sends for MM2; kept as a fallback to try
  D7 01     -- Magic Mouse 1
Apple's filter swallows report 0x90 and exposes Feature 0x47 (Battery Strength 0..100) in its rewritten descriptor.
Finger layout (8 bytes from offset 14) is identical in Apple's parser and Linux.
"""
from __future__ import annotations

from dataclasses import dataclass, field

BT_VENDOR_APPLE = 0x004C
USB_VENDOR_APPLE = 0x05AC
PID_MAGICMOUSE2 = 0x0269
PID_MAGICMOUSE2_USBC = 0x0323

REPORT_TOUCH = 0x12
REPORT_BATTERY = 0x90
FEATURE_ENABLE_MT = bytes([0xF1, 0x02, 0x01])        # Apple driver, MM2 over BT
FEATURE_ENABLE_MT_ALT = bytes([0xF1, 0xC8, 0x09])    # Linux hid-magicmouse, MM2
REPORT_BATTERY_FEATURE = 0x47                         # in Apple's rewritten descriptor

# Surface coordinate range reported by the mouse (Linux hid-magicmouse constants)
X_MIN, X_MAX = -1100, 1258
Y_MIN, Y_MAX = -1589, 2047

TOUCH_STATE_MASK = 0xF0
TOUCH_STATE_NONE = 0x00
TOUCH_STATE_START = 0x30
TOUCH_STATE_DRAG = 0x40


def _s12(v: int) -> int:
    v &= 0xFFF
    return v - 0x1000 if v & 0x800 else v


@dataclass
class Touch:
    id: int
    x: int            # X_MIN..X_MAX (left -> right)
    y: int            # Y_MIN..Y_MAX (front of mouse = larger y)
    major: int        # ellipse axes (raw units, x4 ~ surface units)
    minor: int
    size: int
    orientation: int  # -32..31
    state: int

    # Observed states (state >> 4): 1/2 approaching, 3 touch start, 4 drag, 5..7 lifting.
    @property
    def down(self) -> bool:
        """Finger is on the surface (touch start or drag)."""
        return self.state in (TOUCH_STATE_START, TOUCH_STATE_DRAG)

    @property
    def present(self) -> bool:
        """Reported at all (approaching, on surface or lifting)."""
        return (self.state & TOUCH_STATE_MASK) != TOUCH_STATE_NONE

    @property
    def nx(self) -> float:
        return (self.x - X_MIN) / (X_MAX - X_MIN)

    @property
    def ny(self) -> float:
        return (self.y - Y_MIN) / (Y_MAX - Y_MIN)


@dataclass
class TouchFrame:
    buttons: int
    dx: int
    dy: int
    touches: list[Touch] = field(default_factory=list)
    raw: bytes = b""


def parse_touch(tdata: bytes) -> Touch:
    t = tdata
    return Touch(
        id=((t[6] << 2) | (t[5] >> 6)) & 0xF,
        x=_s12(((t[1] & 0x0F) << 8) | t[0]),
        y=-_s12((t[2] << 4) | (t[1] >> 4)),
        major=t[3],
        minor=t[4],
        size=t[5] & 0x3F,
        orientation=(t[6] >> 2) - 32,
        state=t[7] & TOUCH_STATE_MASK,
    )


def parse_report(data: bytes) -> TouchFrame | None:
    """Parse a 0x12 report (from a raw vendor collection or USB). None if not a touch report."""
    if not data or data[0] != REPORT_TOUCH:
        return None
    n = len(data)
    if n < 6:
        return None
    dx = int.from_bytes(data[2:4], "little", signed=True)
    dy = int.from_bytes(data[4:6], "little", signed=True)
    frame = TouchFrame(buttons=data[1], dx=dx, dy=dy, raw=bytes(data))
    if n >= 14:
        for i in range(min((n - 14) // 8, 15)):
            off = 14 + 8 * i
            frame.touches.append(parse_touch(data[off:off + 8]))
    return frame


@dataclass
class Battery:
    percent: int
    flags: int

    @property
    def charging(self) -> bool:
        # Observed flags 0x00 on battery; bit meaning still being confirmed by RE / capture.
        return bool(self.flags & 0x02)


def parse_battery(data: bytes) -> Battery | None:
    if len(data) >= 3 and data[0] == REPORT_BATTERY and data[2] <= 100:
        return Battery(percent=data[2], flags=data[1])
    return None


def is_magic_mouse2(vid: int, pid: int) -> bool:
    return vid in (BT_VENDOR_APPLE, USB_VENDOR_APPLE) and pid in (PID_MAGICMOUSE2, PID_MAGICMOUSE2_USBC)
