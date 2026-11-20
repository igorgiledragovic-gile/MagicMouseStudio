"""Change values in the REAL user settings from outside the app (stops the app first so it cannot overwrite them).
usage: pythonw tools/apply_settings.py [--restart] key=value [key=value ...]     e.g.  rotate=0 language=sr
Values are parsed as JSON when possible (0, true, "x"), otherwise kept as text.
Run it outside any packaged-app container (e.g. through Explorer), otherwise %LOCALAPPDATA% is virtualized."""
import json, os, pathlib, subprocess, sys, time

APP = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from mmstudio.settings import SETTINGS_FILE, Settings   # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith("--")]
restart = "--restart" in sys.argv
log = SETTINGS_FILE.parent / "apply_settings.log"
INSTALLED = pathlib.Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "MagicMouse Studio" / "MagicMouseStudio.exe"


def say(msg):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")


# 1. stop running instances (installed .exe and the development copy)
ps = ("Get-CimInstance Win32_Process | ? { $_.Name -eq 'MagicMouseStudio.exe' -or $_.CommandLine -match 'MagicMouseStudio\\\\app\\\\run.py' } | "
      "% { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], creationflags=0x08000000, timeout=30)
time.sleep(1.5)

# 2. write
s = Settings.load()
for kv in args:
    k, _, v = kv.partition("=")
    if not hasattr(s, k):
        say(f"unknown setting {k!r} - skipped")
        continue
    try:
        val = json.loads(v)
    except ValueError:
        val = v
    old = getattr(s, k)
    if not isinstance(val, type(old)):
        say(f"{k}: {val!r} has the wrong type (expected {type(old).__name__}) - skipped")
        continue
    setattr(s, k, val)
    say(f"{k}: {old!r} -> {val!r}")
s.save()

# 3. start again (installed copy if present)
if restart:
    if INSTALLED.exists():
        subprocess.Popen([str(INSTALLED)], cwd=str(INSTALLED.parent), creationflags=0x00000008 | 0x00000200)
    else:
        pyw = pathlib.Path(sys.executable).with_name("pythonw.exe")
        subprocess.Popen([str(pyw if pyw.exists() else sys.executable), str(APP / "run.py")], cwd=str(APP),
                         creationflags=0x00000008 | 0x00000200)
    say("app restarted")
