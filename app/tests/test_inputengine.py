"""Engine tests with synthetic frames; winput is replaced by a recorder (nothing is injected)."""
import pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from mmstudio import inputengine, protocol, winput
from mmstudio.settings import Settings, KIND_MIDDLE, MIDDLE_THREE

calls = []
winput.wheel = lambda d, h=False: calls.append(("wheel", "h" if h else "v", d))
winput.click = lambda b: calls.append(("click", b))
winput.button = lambda b, down: calls.append(("btn", b, down))
winput.chord = lambda *v: calls.append(("chord",) + v)
winput.browser_back = lambda: calls.append(("back",))
winput.browser_forward = lambda: calls.append(("forward",))

CX = (protocol.X_MIN + protocol.X_MAX) // 2


def T(i, x, y, st=protocol.TOUCH_STATE_DRAG, size=10):
    return protocol.Touch(i, x, y, 100, 80, size, 0, st)


def F(*touches, buttons=0, dx=0, dy=0):
    return protocol.TouchFrame(buttons, dx, dy, list(touches))


def run(eng, frames, dt=0.011):
    for fr in frames:
        eng.feed(fr)
        time.sleep(dt)


def fresh(**kw):
    calls.clear()
    s = Settings()
    for k, v in kw.items():
        setattr(s, k, v)
    return inputengine.InputEngine(s)


def test_scroll_wheel_like_vertical():
    e = fresh(scroll_smooth=False, scroll_accelerated=False)
    # finger moves towards the palm (y grows) by 1200 units in 30 steps
    run(e, [F(T(1, CX, -800 + 40 * k)) for k in range(31)] + [F()])
    wheels = [c for c in calls if c[0] == "wheel"]
    assert wheels and all(c[1] == "v" for c in wheels)
    # inverse ON (MU default, user-confirmed) = like a wheel: finger to the palm -> scroll DOWN (negative)
    assert sum(c[2] for c in wheels) < 0 and all(abs(c[2]) % 120 == 0 for c in wheels)


def test_scroll_natural_direction():
    e = fresh(scroll_smooth=False, scroll_accelerated=False, scroll_inverse_v=False)
    run(e, [F(T(1, CX, -800 + 40 * k)) for k in range(31)] + [F()])
    assert sum(c[2] for c in calls if c[0] == "wheel") > 0


def test_no_horizontal_scroll_by_default():
    e = fresh(swipe_navigate_left=False, swipe_navigate_right=False)
    run(e, [F(T(1, -900 + 40 * k, 0)) for k in range(40)] + [F()])
    assert not [c for c in calls if c[0] == "wheel"]


def test_tap1_left_and_right():
    e = fresh(tap1=True)
    run(e, [F(T(1, -700, -1200, protocol.TOUCH_STATE_START)), F(T(1, -700, -1200)), F()])
    assert ("click", winput.BTN_LEFT) in calls
    calls.clear()
    time.sleep(0.3)
    run(e, [F(T(2, 900, -1200, protocol.TOUCH_STATE_START)), F(T(2, 900, -1200)), F()])
    assert ("click", winput.BTN_RIGHT) in calls


def test_tap_outside_tap_area_ignored():
    e = fresh(tap1=True)
    run(e, [F(T(1, -700, 1500)), F(T(1, -700, 1500)), F()])   # far back: beyond tap_area_from_top
    assert not [c for c in calls if c[0] == "click"]


def test_tap2_secondary_and_tap3_middle():
    e = fresh(tap2=True, tap3=True)
    run(e, [F(T(1, -400, -900), T(2, 400, -900)), F(T(1, -400, -900), T(2, 400, -900)), F()])
    assert ("click", winput.BTN_RIGHT) in calls
    calls.clear(); time.sleep(0.35)
    run(e, [F(T(1, -600, -900), T(2, 0, -950), T(3, 600, -900)), F(T(1, -600, -900), T(2, 0, -950), T(3, 600, -900)), F()])
    assert ("click", winput.BTN_MIDDLE) in calls


def test_flick_navigation():
    e = fresh()
    run(e, [F(T(1, -800 + 120 * k, -500)) for k in range(12)] + [F()])
    assert ("back",) in calls or ("forward",) in calls
    assert not [c for c in calls if c[0] == "wheel"]


def test_two_finger_swipe_desktop():
    e = fresh()
    run(e, [F(T(1, 600 - 60 * k, -700), T(2, 1000 - 60 * k, -700)) for k in range(14)] + [F()])
    chords = [c for c in calls if c[0] == "chord"]
    assert chords and chords[0][1:3] == (winput.VK_CONTROL, winput.VK_LWIN)


def _click(e, *touches):
    e.feed(F(*touches))
    e.feed(F(*touches, buttons=1))
    out = e.hook.clicks[-1]
    e.feed(F())
    return out


class FakeHook:
    def __init__(self):
        self.touches = 0
        self.clicks = []
        self.cfg = None

    def touch(self):
        self.touches += 1

    def set_click(self, buttons):
        self.clicks.append(buttons)

    def config(self, *a):
        self.cfg = a


def test_click_mapping_split_middle_swap():
    e = fresh(middle_click=True, middle_click_kind=MIDDLE_THREE)
    e.hook = FakeHook()
    assert _click(e, T(1, -800, -1300)) == [winput.BTN_LEFT]
    # finger on the right side -> secondary, whatever the Apple driver reports
    assert _click(e, T(2, 1000, -1300)) == [winput.BTN_RIGHT]
    assert _click(e, T(1, -600, -1200), T(2, 0, -1250), T(3, 600, -1200)) == [winput.BTN_MIDDLE]
    e.s.swap_buttons = True
    assert _click(e, T(1, -800, -1300)) == [winput.BTN_RIGHT]
    e.s.swap_buttons = False
    e.s.tap1, e.s.tap1_ignore_real_click = True, True
    assert _click(e, T(1, -800, -1300)) == []          # silent mode: physical click swallowed


def test_native_hook_state():
    e = fresh()
    e.hook = FakeHook()
    e.feed(F(T(1, 0, 0)))
    assert e.hook.touches == 1 and e.hook.cfg == (True, True, True)
    e.s.scroll_owner = "apple"
    e.set_enabled(False)
    assert e.hook.cfg == (False, True, False)


def test_speed_changes_amount():
    def total(speed):
        e = fresh(scroll_smooth=True, scroll_accelerated=False, scroll_speed=speed)
        run(e, [F(T(1, CX, -800 + 40 * k)) for k in range(31)] + [F()], dt=0)
        return abs(sum(c[2] for c in calls if c[0] == "wheel"))
    slow, mid, fast = total(1), total(60), total(100)
    assert slow < mid / 5 and fast > mid * 3, (slow, mid, fast)

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
