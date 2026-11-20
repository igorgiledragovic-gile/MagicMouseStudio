"""MagicMouse Studio self-check (no admin needed). Prints a verdict per component and writes
%LOCALAPPDATA%\\MagicMouseStudio\\selfcheck.txt.  usage: python tools/selfcheck.py"""
import os, pathlib, subprocess, sys, time
APP = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from mmstudio.settings import DATA_DIR   # noqa: E402

lines = []


def say(ok, name, detail=""):
    tag = {True: "OK  ", False: "FAIL", None: "INFO"}[ok]
    s = f"[{tag}] {name}" + (f" — {detail}" if detail else "")
    print(s, flush=True)
    lines.append(s)


py = sys.executable

# 1. driver
try:
    from mmstudio.driverlink import DriverLink
    d = DriverLink()
    s = d.status()
    d.close()
    say(True, "drajver mmsfilter", f"v{s.version >> 16}.{(s.version >> 8) & 0xFF}, uređaja {s.devices}, frame-ova od starta {s.frames_seen}, "
                                   f"baterija {s.battery_percent if s.battery_percent >= 0 else '?'} %")
except OSError as e:
    say(False, "drajver mmsfilter", f"kontrolni uređaj nije dostupan ({e}). Instalacija: driver\\install-bt.ps1 (admin)")

# 2. SendInput health (a dead low-level hook anywhere on the system blocks injected input)
code = ("import ctypes,sys; sys.path.insert(0, r'%s'); from mmstudio import winput; "
        "import time; winput.wheel(1); t=time.time()\n"
        "while winput.health()[2]==0 and time.time()-t<4: time.sleep(0.05)\n"
        "print('SENT' if winput.health()[2] else 'BLOCKED'); import os; os._exit(0)") % APP
# NOTE: a child stuck inside SendInput cannot be killed (it waits in the kernel), so never wait for it:
# write its answer to a file, give it 8 s, then just read the file.
res = DATA_DIR / "selfcheck_sendinput.txt"
DATA_DIR.mkdir(parents=True, exist_ok=True)
res.unlink(missing_ok=True)
code = code.replace("print('SENT' if winput.health()[2] else 'BLOCKED')",
                    "open(r'%s','w').write('SENT' if winput.health()[2] else 'BLOCKED')" % res)
subprocess.Popen([py, "-I", "-c", code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                 creationflags=0x08000000)          # CREATE_NO_WINDOW
for _ in range(80):
    if res.exists() and res.read_text().strip():
        break
    time.sleep(0.1)
out = res.read_text().strip() if res.exists() else "BLOCKED"
say(out == "SENT", "Windows prima ubačeni ulaz (SendInput)",
    "radi" if out == "SENT" else "BLOKIRAN — neki proces ima zaglavljen hook za miš; restartuj računar")

# 3. native hook
try:
    from mmstudio.hook import MouseHook
    h = MouseHook()
    ok = h.start()
    st = h.stats()
    h.stop()
    say(ok, "nativni hook (mmshook.dll)", "pokreće se i gasi" if ok else f"greška {h.error or st.error}")
except Exception as e:     # noqa: BLE001
    say(False, "nativni hook (mmshook.dll)", repr(e))

# 4. unit tests
for t in ("test_protocol.py", "test_inputengine.py", "test_i18n.py", "test_widgets.py"):
    r = subprocess.run([py, "-I", str(APP / "tests" / t)], capture_output=True, text=True, timeout=120)
    n = r.stdout.count("ok ")
    say(r.returncode == 0, f"testovi {t}", f"{n} prošlo" if r.returncode == 0 else (r.stderr.strip().splitlines() or ["?"])[-1])

# 5. zombie processes of older versions
try:
    ps = subprocess.run(["powershell", "-NoProfile", "-Command",
                         "Get-CimInstance Win32_Process | ? { $_.CommandLine -match 'MagicMouse' } | "
                         "% { $p=Get-Process -Id $_.ProcessId -EA SilentlyContinue; if ($p -and $p.HasExited) { $_.ProcessId } }"],
                        capture_output=True, text=True, timeout=30).stdout.split()
    say(not ps, "zaglavljeni stari procesi", "nema" if not ps else f"PID {', '.join(ps)} — nestaju tek posle restarta")
except Exception:          # noqa: BLE001
    pass

DATA_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "selfcheck.txt").write_text(time.strftime("%Y-%m-%d %H:%M:%S\n") + "\n".join(lines) + "\n", encoding="utf-8")
print("\nRezultat sačuvan u", DATA_DIR / "selfcheck.txt")
