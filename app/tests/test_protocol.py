import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from mmstudio import protocol as p


def test_battery_capture():
    # real capture from this machine (2026-11-15): 90 00 58 -> 88 %
    b = p.parse_battery(bytes.fromhex("900058"))
    assert b and b.percent == 88


def test_plain_mouse_report():
    f = p.parse_report(bytes.fromhex("1200ebffdeff0000"))
    assert f and (f.dx, f.dy) == (-21, -34) and f.touches == []


def test_touch_decode_roundtrip():
    # build one touch: x=-300, y=+500, major=40, minor=30, size=10, orient=0, id=3, state=DRAG
    x, y, ident = -300, 500, 3
    ux, uy = x & 0xFFF, (-y) & 0xFFF
    t = bytearray(8)
    t[0] = ux & 0xFF
    t[1] = ((ux >> 8) & 0x0F) | ((uy & 0x0F) << 4)
    t[2] = (uy >> 4) & 0xFF
    t[3], t[4] = 40, 30
    t[5] = (10 & 0x3F) | ((ident & 0x3) << 6)
    t[6] = ((0 + 32) << 2) | (ident >> 2)
    t[7] = p.TOUCH_STATE_DRAG
    report = bytes([0x12, 0, 0, 0, 0, 0] + [0] * 8) + bytes(t)
    f = p.parse_report(report)
    assert len(f.touches) == 1
    tc = f.touches[0]
    assert (tc.x, tc.y, tc.id, tc.major, tc.minor, tc.size, tc.orientation) == (x, y, ident, 40, 30, 10, 0)
    assert tc.down


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
