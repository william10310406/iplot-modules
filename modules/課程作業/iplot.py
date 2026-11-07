"""課程作業：出作業的老師從範本寫一份作業、在 iPLoT 裡選一個 case 看結果、按一顆鈕打包成學生包。按下去：列出這台電腦上的課。"""

import ast
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ICON = "📚"


def _framework():
    """框架在 框架/course.py：放進 sys.path 讀一次，每次都重讀（框架更新後不用重開 iPLoT）。"""
    sys.path.insert(0, str(HERE / "框架"))
    try:
        import course  # noqa: PLC0415
        return course
    finally:
        sys.path.remove(str(HERE / "框架"))
        sys.modules.pop("course", None)


def _name(file, fallback):
    """課程.py 頂層的 NAME = "…"（只用 ast，不執行）；讀不出來就用資料夾名。"""
    try:
        for node in ast.parse(file.read_text(encoding="utf-8-sig")).body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "NAME"
                    and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
                    and node.value.value.strip()):
                return node.value.value
    except (SyntaxError, ValueError, OSError):
        pass
    return fallback


def _homework_count(folder):
    """一份作業是課裡一個資料夾，裡面有 iplot.py 以外的 .py（按鈕的資料夾只有 iplot.py）。"""
    try:
        return sum(1 for sub in folder.iterdir()
                   if sub.is_dir() and not sub.name.startswith(".")
                   and any(f.suffix == ".py" and f.name != "iplot.py" for f in sub.iterdir() if f.is_file()))
    except OSError:
        return 0


def run(app):
    course = _framework()
    courses = sorted(p for p in HERE.iterdir()
                     if p.is_dir() and not p.name.startswith(".") and (p / course.MARK).is_file())
    if not courses:
        app.log("還沒有課。按「新增一門課」開始")
        return
    for folder in courses:
        venv = "已建" if (folder / ".venv").is_dir() else "還沒建"
        app.log(f"{_name(folder / course.MARK, folder.name)}：{_homework_count(folder)} 份作業；.venv {venv}")
