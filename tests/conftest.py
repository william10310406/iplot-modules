"""測試共用的東西：隔壁的 iPLoT clone、載入 iPLoT 的檔、把開發者自己的 git 設定隔開。"""

import importlib.util
import sys
from pathlib import Path

import pytest

IPLOT = Path(__file__).resolve().parents[2] / "iplot"


@pytest.fixture
def iplot_next_door():
    """隔壁有 iPLoT 的 clone 就回它的路徑，沒有就 skip（對照的測試只在本機有兩個 repo 時跑）。"""
    if not (IPLOT / "core" / "create.py").is_file():
        pytest.skip("隔壁沒有 iPLoT 的 clone")
    return IPLOT


def load_iplot(relpath: str, name: str):
    """載入 iPLoT 的一個檔（例如 load_iplot("core/create.py", "core.create")），回那個模組。
    載入時暫時把 IPLOT 放進 sys.path、不寫 __pycache__；結束時拿掉 sys.path 加的、
    這一次載入的 name 與 core、core.* ——tools/publish.py 一載入就 from core.meta import read_meta。"""
    path_before = list(sys.path)
    modules_before = set(sys.modules)
    bytecode_before = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(IPLOT))
    try:
        spec = importlib.util.spec_from_file_location(name, IPLOT / relpath)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module  # dataclass 要在 sys.modules 找得到自己的模組
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = path_before
        sys.dont_write_bytecode = bytecode_before
        for loaded in set(sys.modules) - modules_before:
            if loaded == name or loaded == "core" or loaded.startswith("core."):
                del sys.modules[loaded]


@pytest.fixture(autouse=True)
def isolated_git(tmp_path, monkeypatch):
    """git 只看一個空的全域設定、不看系統的：開發者自己的 git 設定不混進測試。"""
    config = tmp_path / "gitconfig"
    config.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
