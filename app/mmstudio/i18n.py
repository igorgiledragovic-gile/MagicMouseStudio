"""Tiny translation layer.

Source strings in the code are English and wrapped in _("..."); translations live in
mmstudio/locales/<code>.json as {"English text": "translated text"}.  English is the default; a
missing translation falls back to English.  Placeholders use str.format names: _("Low battery: {pct} %", pct=12).

The master table with all languages is tools/translations.py (it generates the JSON files).
"""
from __future__ import annotations

import json
import os

# 7 languages, every inhabited continent covered (code, native name, right-to-left)
LANGUAGES = [
    ("en", "English", False),               # North America, Oceania, worldwide
    ("sr", "Srpski", False),                # Europe
    ("es", "Español", False),               # South & Central America, Europe
    ("pt", "Português (Brasil)", False),    # South America, Africa
    ("fr", "Français", False),              # Europe, Africa
    ("zh", "中文（简体）", False),             # Asia
    ("ar", "العربية", True),                 # Africa, Middle East
]
DEFAULT = "en"
_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")
_table: dict[str, str] = {}
_current = DEFAULT


def available() -> list[str]:
    return [c for c, _n, _r in LANGUAGES]


def set_language(code: str) -> str:
    """Activate a language; unknown codes fall back to English. Returns the active code."""
    global _table, _current
    code = code if code in available() else DEFAULT
    _table = {}
    if code != DEFAULT:
        try:
            with open(os.path.join(_DIR, f"{code}.json"), encoding="utf-8") as fh:
                _table = json.load(fh)
        except (OSError, ValueError):
            code = DEFAULT
    _current = code
    return code


def current() -> str:
    return _current


def is_rtl(code: str | None = None) -> bool:
    code = code or _current
    return any(c == code and rtl for c, _n, rtl in LANGUAGES)


def _(text: str, **kw) -> str:
    s = _table.get(text) or text
    if kw:
        try:
            return s.format(**kw)
        except (KeyError, IndexError, ValueError):
            return text.format(**kw)
    return s
