"""Set the UI language in the REAL user settings and restart the app.
usage: pythonw tools/apply_language.py <code>      (e.g. sr)
Run it outside any packaged-app container (e.g. through Explorer), otherwise %LOCALAPPDATA% is virtualized."""
import json, os, pathlib, subprocess, sys, time

APP = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from mmstudio import i18n                  # noqa: E402
from mmstudio.settings import SETTINGS_FILE, Settings   # noqa: E402

code = sys.argv[1] if len(sys.argv) > 1 else "en"
assert code in i18n.available(), code
log = SETTINGS_FILE.parent / "apply_language.log"


def say(msg):
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")


# 1. stop running instances (they would overwrite settings.json on exit)
ps = ("Get-CimInstance Win32_Process | ? { $_.CommandLine -match 'MagicMouseStudio\\\\app\\\\run.py' } | "
      "% { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], creationflags=0x08000000, timeout=30)
time.sleep(1.5)

# 2. write the language into the real settings
s = Settings.load()
s.language = code
s.save()
say(f"language={code} written to {SETTINGS_FILE}")

# 3. start the app again
pyw = pathlib.Path(sys.executable).with_name("pythonw.exe")
subprocess.Popen([str(pyw if pyw.exists() else sys.executable), str(APP / "run.py")], cwd=str(APP),
                 creationflags=0x00000008 | 0x00000200)
say("app restarted")
