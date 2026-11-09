"""測試的共同設定。測試只碰「行事曆 2」自己和 pytest 給的暫存資料夾：

- `core` 設成不能 import（iplot.py 找不到它就用後備），所以不會讀到、也不會寫到 iPLoT 的 core/；
- 不寫 .pyc；
- 網路一律用替身，不連任何網址。"""

import datetime
import sys
import types

import pytest

sys.dont_write_bytecode = True
sys.modules["core"] = None  # from core import scan → ImportError

import support  # noqa: E402  要在上面兩行之後；pytest 把 tests/ 放進了 sys.path

sys.path.insert(0, str(support.MODULE))


@pytest.fixture
def root(tmp_path):
    """日記資料夾（空的）。"""
    folder = tmp_path / "diary"
    folder.mkdir()
    return folder


@pytest.fixture
def home(tmp_path):
    """假的 iPLoT 資料夾（FakeApp.home）：只有空的 modules/。"""
    folder = tmp_path / "iPLoT"
    (folder / "modules").mkdir(parents=True)
    return folder


@pytest.fixture
def fake_app(home):
    return support.FakeApp(home)


@pytest.fixture
def settings_file(tmp_path):
    return tmp_path / "設定.json"


@pytest.fixture
def make_api(tmp_path, fake_app, root):
    """造一個 iplot.Api：假 app、日記資料夾在 tmp、LINE 用假的 fetch（同步執行）。url 給了就先寫進設定檔。
    today／now 是這台電腦的本地日期與時間（Api 的 today、now）；clock 是 LINE 那一層的時鐘（台北時間，要跟 today 對得上）。"""
    import iplot
    import line_sync
    import settings

    def build(*, url=None, today=datetime.date(2026, 11, 8), now=datetime.datetime(2026, 11, 8, 21, 45), fetch=None, clock=None,
              spawn=lambda fn: fn(), **kw):
        module = tmp_path / "module"
        module.mkdir(exist_ok=True)
        settings_file = module / "設定.json"
        if url:
            settings.update(settings_file, lambda data: data.setdefault("LINE", {}).update({"url": url}))
        fetch = fetch or support.FakeLine(today=today.isoformat())
        clock = clock or support.Clock()

        def factory(settings_path, cache_path, on_success):
            return line_sync.Sync(settings_path, cache_path, fetch=fetch, clock=clock, spawn=spawn, on_success=on_success)

        api = iplot.Api(fake_app, settings_file, default_root=root, platform="linux", environ={}, today=lambda: today,
                        now=lambda: now, dock_icon=lambda *args: True, line_factory=factory, **kw)
        return types.SimpleNamespace(api=api, app=fake_app, fetch=fetch, clock=clock, settings=settings_file, root=root, module=module,
                                     ledger=module / "line_copied.json", cache=module / "line_cache.json", sync=api._line)

    return build
