"""問課的名字，建一門新的課。"""
# 課程作業框架產生的墊片（改了會被換掉；要自己寫格子，把這一行拿掉）
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
TITLE = '新增一門課'
FRAMEWORK = next(p for p in HERE.parents if (p / "框架" / "course.py").is_file()) / "框架"
sys.modules.pop("course", None)  # 每次都讀框架現在那一份
sys.path.insert(0, str(FRAMEWORK))
try:
    import course
finally:
    sys.path.remove(str(FRAMEWORK))


def run(app):
    course.new_course(app, HERE.parent)
