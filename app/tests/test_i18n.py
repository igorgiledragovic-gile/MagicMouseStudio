"""Every _("...") string in the code must exist in every locale with identical {placeholders}."""
import ast, json, pathlib, re, string, sys
APP = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from mmstudio import i18n

DYNAMIC = {"left", "right", "middle"}          # passed to _() through a variable (inputengine button names)


def used_keys() -> set[str]:
    keys = set(DYNAMIC)
    for py in (APP / "mmstudio").rglob("*.py"):
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_" and node.args \
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                keys.add(node.args[0].value)
    return keys


def fields(s: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(s) if f}


def test_all_languages_complete():
    keys = used_keys()
    assert len(keys) > 150, len(keys)
    problems = []
    for code in i18n.available():
        if code == i18n.DEFAULT:
            continue
        table = json.loads((APP / "mmstudio" / "locales" / f"{code}.json").read_text(encoding="utf-8"))
        for k in sorted(keys):
            v = table.get(k)
            if not v:
                problems.append(f"{code}: missing {k!r}")
            elif fields(v) != fields(k):
                problems.append(f"{code}: placeholders differ in {k!r}: {fields(v)} vs {fields(k)}")
    assert not problems, "\n".join(problems)


def test_switching_and_fallback():
    assert i18n.set_language("sr") == "sr" and i18n._("Scrolling") == "Skrolovanje"
    assert i18n._("Low battery: {name} {pct} %.", name="MM", pct=7) == "Slaba baterija: MM 7 %."
    assert i18n.set_language("ar") == "ar" and i18n.is_rtl()
    assert i18n.set_language("xx") == "en" and i18n._("Scrolling") == "Scrolling"
    assert i18n._("no such text {a}", a=1) == "no such text 1"
    assert len(i18n.LANGUAGES) <= 7


def test_no_serbian_left_in_code():
    bad = []
    for py in (APP / "mmstudio").rglob("*.py"):
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and re.search(r"[čćšžđČĆŠŽĐ]", node.value) \
                    and not node.value.startswith(("All user settings", "User-mode", "MagicMouse")):
                bad.append(f"{py.name}:{node.lineno} {node.value[:60]!r}")
    assert not bad, "\n".join(bad)


if __name__ == "__main__":
    unused = set()
    table = json.loads((APP / "mmstudio" / "locales" / "sr.json").read_text(encoding="utf-8"))
    unused = set(table) - used_keys()
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
    if unused:
        print("unused keys:", sorted(unused))
