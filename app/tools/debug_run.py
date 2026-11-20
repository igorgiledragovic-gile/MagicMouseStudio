"""Run the app with periodic all-thread stack dumps (for hangs) into %LOCALAPPDATA%\\MagicMouseStudio\\stacks.log."""
import faulthandler, os, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from mmstudio.settings import DATA_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)
log = open(DATA_DIR / "stacks.log", "w", encoding="utf-8")
faulthandler.dump_traceback_later(15, repeat=True, file=log)
from mmstudio.ui.main import main
sys.exit(main())
