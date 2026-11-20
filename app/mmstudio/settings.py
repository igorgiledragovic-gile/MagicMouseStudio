"""All user settings (JSON in %LOCALAPPDATA%\\MagicMouseStudio\\settings.json).

The set and the defaults mirror what Magic Utilities 3.1.6.4 stored for this user's mouse
(HKCU\\SOFTWARE\\MagicUtilities\\MagicMouse\\Devices\\dtMM2-<MAC>, backup 2026-11-19); the MU name is
noted next to each field.  Distances are raw surface units (X -1100..1258, Y -1589..2047; Y measured
from the FRONT edge where noted), times in ms.
"""
from __future__ import annotations

import json
import os
import pathlib
from dataclasses import asdict, dataclass, fields

DATA_DIR = pathlib.Path(os.environ.get("LOCALAPPDATA", ".")) / "MagicMouseStudio"
SETTINGS_FILE = DATA_DIR / "settings.json"
SETTINGS_VERSION = 2



def install_language() -> str:
    """First start of an installed copy: the language picked in Setup.exe (language.txt next to the .exe)."""
    import sys
    if getattr(sys, "frozen", False):
        try:
            code = pathlib.Path(sys.executable).with_name("language.txt").read_text(encoding="utf-8-sig").strip()
            if code:
                return code
        except OSError:
            pass
    return "en"


# click kinds (MU *Kind values)
KIND_PRIMARY, KIND_SECONDARY, KIND_MIDDLE = 0, 1, 3
# middle-click variants (usMiddleClickKind)
MIDDLE_ONE_FINGER_CENTER, MIDDLE_ANY_TWO, MIDDLE_WIDE_TWO, MIDDLE_THREE = 0, 1, 2, 3
# scroll fingers (usScrollFingers)
SCROLL_ONE, SCROLL_ONE_OR_TWO, SCROLL_TWO = 0, 1, 2
# who handles scroll / clicks
OWNER_STUDIO, OWNER_APPLE = "studio", "apple"


@dataclass
class Settings:
    version: int = SETTINGS_VERSION

    # ---- skrolovanje (UserSettings) ----
    scroll_owner: str = OWNER_STUDIO          # studio engine or keep Apple driver's scroll
    scrolling: bool = True                    # usScrolling
    scroll_fingers: int = SCROLL_ONE          # usScrollFingers
    scroll_smooth: bool = False               # usScrollingSmooth
    scroll_inverse_v: bool = True             # usScrollingInverseVerti  (ON = like a wheel; OFF = natural/macOS)
    scroll_inverse_h: bool = True             # usScrollingInverseHori
    scroll_orthogonal_only: bool = True       # usScrollOrthogonalOnly
    scroll_no_horizontal: bool = True         # usScrollingNoHorizontal
    scroll_accelerated: bool = True           # usScrollAccelerated
    scroll_speed: int = 60                    # usScrollSpeed (1..100)
    scroll_stop_on_mouse_move: bool = False   # usScrollStopOnMouseMove
    scroll_momentum: bool = True              # inertia after lift (smooth mode only)

    # ---- klikovi ----
    click_owner: str = OWNER_STUDIO
    swap_buttons: bool = False                # usSwapLeftRightButtons
    left_handed: bool = False                 # dsLeftHanded
    button_split: int = 55                    # dsLeftRightButtonSplit (% of width from the left)
    simultaneous_clicks: bool = False         # usSimultaneousPrimaryAndSecondaryClicks
    middle_click: bool = False                # usMiddleClick
    middle_click_kind: int = MIDDLE_ONE_FINGER_CENTER   # usMiddleClickKind
    pointer_speed: int = 2                    # usBasePointerSpeed (needs driver support; not applied)

    # ---- tap (m1/m2/m3) ----
    tap1: bool = False                        # m1TapToClick
    tap1_left: bool = True                    # m1TapToClickLeft
    tap1_left_kind: int = KIND_PRIMARY        # m1TapToClickLeftKind
    tap1_middle: bool = False                 # m1TapToClickMiddle
    tap1_middle_kind: int = KIND_MIDDLE       # m1TapToClickMiddleKind
    tap1_right: bool = True                   # m1TapToClickRight
    tap1_right_kind: int = KIND_SECONDARY     # m1TapToClickRightKind
    tap1_use_tap_area: bool = True            # m1TapUseTapArea
    tap1_filter_ignore_areas: bool = True     # m1TapFilterIgnoreAreas
    tap1_ignore_real_click: bool = False      # m1TapIgnoreRealClick
    double_tap_drag: bool = False             # m1DoubleTapDrag / m1DoubleTapDragging
    tap2: bool = False                        # m2TapToClick
    tap2_kind: int = KIND_SECONDARY           # m2TapToClickKind
    tap2_use_tap_area: bool = False           # m2TapUseTapArea
    tap2_filter_ignore_areas: bool = True     # m2TapFilterIgnoreAreas
    tap3: bool = False                        # m3TapToClick
    tap3_kind: int = KIND_MIDDLE              # m3TapToClickKind
    tap3_use_tap_area: bool = False           # m3TapUseTapArea
    tap3_filter_ignore_areas: bool = False    # m3TapFilterIgnoreAreas

    # ---- geste ----
    swipe_navigate_left: bool = True          # usSwipeNavigateLeft  (1 finger flick = back/forward)
    swipe_navigate_right: bool = True         # usSwipeNavigateRight
    swap_navigate: bool = True                # usSwapNavigate
    swipe2_left: bool = True                  # m2SwipeLeft  (virtual desktop)
    swipe2_right: bool = True                 # m2SwipeRight
    swipe2_up: bool = False                   # m2SwipeUp    (Task View)
    swipe2_down: bool = False                 # m2SwipeDown  (Desktop View)
    swap_desktop_direction: bool = False      # dasSwapDesktopNavigationDirection
    taskview_toggle_mode: bool = False        # dasTaskViewDesktopToggleMode

    # ---- zone (EngineSettings) ----
    ignore_side_left: int = 150               # esIgnoreSideTouchesLeft
    ignore_side_right: int = 150              # esIgnoreSideTouchesRight
    ignore_bottom: int = 900                  # esIgnoreBottomTouches (from the back edge)
    tap_area_from_top: int = 1600             # esTapToClickFromTop (from the front edge)
    middle1_start: int = 819                  # esMiddleClick1Start (from the left edge)
    middle1_end: int = 1638                   # esMiddleClick1End
    middle2_min_distance: int = 1228          # esMiddleClick2MinDistance
    show_zones: bool = False

    # ---- napredno (EngineSettings) ----
    swipe_h_offset: int = 75                  # esSwipeHoriOffset  (units per frame, 1-finger flick)
    swipe_v_offset: int = 45                  # esSwipeVertiOffset
    swipe2_h_offset: int = 35                 # esSwipe2HoriOffset (2 fingers)
    swipe2_v_offset: int = 40                 # esSwipe2VertiOffset
    scroll_step_factor: int = 120             # esScrollStepFactor (wheel delta of one notch)
    scroll_h_offset: int = 225                # esScrollHoriOffset (dead zone before scrolling)
    scroll_v_offset: int = 225                # esScrollVertiOffset
    tap_delay: int = 200                      # esTapDelay
    tap_offset_allowed: int = 80              # esTapOffsetAllowed
    tap_sense: int = 7                        # esTapSense (minimum touch size)
    double_tap_drag_min: int = 100            # esDoubleTapDragMinDelay
    double_tap_drag_max: int = 200            # esDoubleTapDragMaxDelay
    swipe_navi_block: int = 300               # esSwipeNaviBlockTime
    swipe_other_block: int = 300              # esSwipeOtherBlockTime
    stop_scroll_move_offset: int = 2          # esStopScrollMoveOffset

    # ---- baterija (App / DeviceAppSettings) ----
    battery_alerts: bool = True               # !asDontShowBatteryAlerts
    battery_warning: int = 10                 # asBatteryWarningPercent
    battery_critical: int = 5                 # asBatteryCriticalPercent
    battery_show_charged: int = 50            # asBatteryShowChargedPercent
    battery_show_fully_charged: bool = True   # BatteryShowFullyCharged
    battery_snooze_until: float = 0.0         # BatteryNextAlert (epoch seconds)

    # ---- aplikacija / uređaj ----
    language: str = "en"                      # UI language (i18n.LANGUAGES); English by default
    color: str = "silver"                     # DeviceColor
    device_name: str = "Magic Mouse 2"        # DeviceNameUser
    live_touches: bool = True                 # dsLiveTouches
    show_trails: bool = True
    show_labels: bool = True
    rotate: int = 0
    mirror_x: bool = False
    mirror_y: bool = False
    autostart: bool = True                    # asAutoStart
    start_minimized: bool = False             # asStartMinimized
    show_hints: bool = True                   # asShowHints

    @classmethod
    def load(cls) -> "Settings":
        try:
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            s = cls()
            s.language = install_language()
            return s
        s = cls()
        known = {f.name: f for f in fields(cls)}
        for k, v in raw.items():
            if k in known and k != "version" and isinstance(v, type(getattr(s, k))):
                setattr(s, k, v)
        # v1 -> v2 renames
        if raw.get("version", 1) < 2:
            if "low_battery" in raw:
                s.battery_warning = int(raw["low_battery"])
            if "critical_battery" in raw:
                s.battery_critical = int(raw["critical_battery"])
        return s

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        tmp.replace(SETTINGS_FILE)
