"""面板交來的錯誤（角色 panel.error，D110、D150、D162）：要不要自動問「要回報嗎？」，與 logs/last-error.json。
以前在面板（ui/errlog.py）：面板不該知道「回報與討論」要什麼、也不該知道科學計算的學生作業長什麼樣子。

logs/last-error.json 是這個模組自己寫、自己讀的（report.last_error）：沒遮過，只放在這台電腦（logs/ 不進 git、不進包）。"""

import contextlib
import dataclasses
import json
import time
import unicodedata
from pathlib import Path


def student_homework(error) -> bool:
    """出錯的位置是不是「科學計算」收進來的學生作業檔（D150 修訂）。學生的程式出錯是常態、不是 iPLoT 的 bug，
    不自動問、也不當成「最近一次的錯誤」（免得被附進公開的回報）；那一列的「回報這個問題」照樣能按。
    收作業把它放成 <課程>/<HKn>/<學生>/iplot.py，旁邊是殼 hk_page.py、沒有 t2026fscSpace/，課程資料夾有 hk_tk.py。
    照 modules/科學計算/hk_tk.py 的 course_root、_is_new_folder、_is_student 判斷資料夾的樣子，不看名字猜；
    出錯的位置是 error.file（traceback 裡、正在跑的模組資料夾裡最內層的那一格），正在跑的模組就是那個學生資料夾。
    殼（hk_page.py）裡出的錯照常問：那是 iPLoT 這邊的程式。"""
    if error.source != "module" or error.file is None or error.module is None:
        return False
    file = Path(error.file)
    student = file.parent
    hk, course = student.parent, student.parent.parent
    try:
        return (file.name == "iplot.py" and file.is_file()
                and unicodedata.normalize("NFC", student.name) == unicodedata.normalize("NFC", error.module)
                and student.is_dir() and not student.is_symlink() and (student / "hk_page.py").is_file()
                and not (student / "t2026fscSpace").is_dir() and (course / "hk_tk.py").is_file()
                and not (student / "hk_tk.py").exists() and not (hk / "hk_tk.py").exists())
    except OSError:
        return False


def write(home: Path, error, sentence: str, recent: list[str]) -> None:
    """把這一筆錯誤與那時候最近的訊息寫進 logs/last-error.json（整份換掉）。寫不了（唯讀、磁碟滿了、孤立的代理字元）
    就算了。"""
    data = {**dataclasses.asdict(error), "file": None if error.file is None else str(error.file),
            "sentence": sentence, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "recent": recent}
    with contextlib.suppress(OSError, ValueError):
        (home / "logs").mkdir(exist_ok=True)
        text = json.dumps(data, ensure_ascii=False, indent=1)
        temp = home / "logs" / "last-error.json.tmp"
        temp.write_text(text, encoding="utf-8", errors="surrogateescape")
        temp.replace(home / "logs" / "last-error.json")


def worth_reporting(error, own_name: str) -> bool:
    """面板該不該自動問「要回報嗎？」：自己的錯誤（它壞了的時候，不能把人原本要回報的那一筆蓋掉）與學生作業的不算。"""
    return error.module != own_name and not student_homework(error)
