"""行事曆的網頁（D91）：從一天一個資料夾產生日、月、年、綜合四種頁。

本機版寫在資料夾本身（<資料夾>/index.html、<年>/index.html、<年>/<月>/index.html、<年>/<月>/<日>/index.html）；
公開版寫在 <資料夾>/發佈/，只有打開「公開」的日子，每頁加 noindex（publish）。
每一頁：樣式寫在頁面裡、跟著系統的深色模式；不用 JS、不載入外部資源、連結全是相對路徑；文字一律 html.escape，
檔名一律 urllib.parse.quote。存一天時連前一個、後一個有內容的日子與相鄰的月一起重產（設計第 15 節第 5 條）。
（設計原文叫 site.py：site 是 Python 標準庫的名字，import site 拿到的是它，所以叫 pages.py。）"""

import bisect
import calendar
import html
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

import diary
import photos

PUBLISH = "發佈"
WEEKDAYS = "日一二三四五六"
WEEKDAY_OF = "一二三四五六日"  # date.weekday()：星期一是 0
RECENT = 30
CELL_CHARS = 20
RECENT_IMAGES = 4
LABELS = (("行程", "行程"), ("看到", "看到了什麼"), ("做了", "做了什麼"))
UNREADABLE = "讀不到這個檔（不是 UTF-8），沒有覆寫它"
NO_HEIC = "這張是 HEIC，Chrome 看不到（Safari 看得到）"
EMPTY_DAY = "這一天沒有內容"
NOT_PUBLISHED = "{date} {name}：沒放上網路：{why}"
HEIC_NOT_PUBLISHED = "HEIC 不放上網路，轉成 JPG 才會"
STYLE = """
:root { color-scheme: light dark; --bg: #fbfbfd; --fg: #1d1d1f; --muted: #6e6e73; --line: #d2d2d7; --accent: #d93a2b;
  --cell: #ffffff; }
@media (prefers-color-scheme: dark) { :root { --bg: #1c1c1e; --fg: #f5f5f7; --muted: #98989d; --line: #3a3a3c;
  --accent: #ff6b5b; --cell: #2c2c2e; } }
body { margin: 0 auto; max-width: 900px; padding: 16px; background: var(--bg); color: var(--fg);
  font: 16px/1.6 -apple-system, "PingFang TC", "Noto Sans TC", sans-serif; }
a { color: var(--accent); text-decoration: none; } a:hover { text-decoration: underline; }
nav.crumbs, nav.pager, .muted { color: var(--muted); font-size: 14px; }
nav.pager { display: flex; justify-content: space-between; margin-top: 24px; }
h1 { font-size: 24px; margin: 8px 0 12px; } h2 { font-size: 17px; margin: 16px 0 4px; }
.text { white-space: pre-wrap; margin: 0; } .mood { font-size: 18px; white-space: pre-wrap; }
.photos { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.photos img { max-width: 100%; max-height: 360px; border-radius: 6px; }
.recent .photos img { max-height: 120px; }
table { border-collapse: collapse; width: 100%; table-layout: fixed; }
th { color: var(--muted); font-weight: normal; font-size: 13px; }
table.month td { border: 1px solid var(--line); height: 84px; vertical-align: top; padding: 4px; background: var(--cell);
  font-size: 13px; overflow: hidden; }
table.month td.empty { background: transparent; border: none; }
table.month td a { display: block; color: var(--fg); height: 100%; }
.n { color: var(--muted); } .first { display: block; }
.months { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 16px; }
table.mini td { text-align: center; font-size: 12px; color: var(--muted); height: 22px; }
article { border-top: 1px solid var(--line); padding: 8px 0 16px; }
"""


def _page(title: str, body: str, public: bool) -> str:
    robots = '<meta name="robots" content="noindex">' if public else ""
    return ('<!doctype html>\n<html lang="zh-Hant"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"{robots}<title>{html.escape(title)}</title><style>{STYLE}</style></head>\n<body>\n{body}\n</body></html>\n")


def _e(text: str) -> str:
    return html.escape(text, quote=True)


def _long_date(date: str) -> str:
    d = diary.parse_date(date)
    return f"{d.year} 年 {d.month} 月 {d.day} 日（{WEEKDAY_OF[d.weekday()]}）"


def _images(day: dict, public: bool, skip: frozenset = frozenset()) -> list[str]:
    """公開版只放 JPEG、PNG、GIF，而且不放 skip 裡的（(日期, 檔名)：發佈時處理不了的那幾張）。"""
    names = day["images"]
    if not public:
        return names
    return [n for n in names if Path(n).suffix.lower() in photos.PUBLISHABLE and (day["date"], n) not in skip]


def _day_path(date: str) -> str:
    return f"{date[:4]}/{date[5:7]}/{date[8:]}"


def _fields(day: dict, public: bool) -> str:
    parts = []
    for field, label in LABELS:
        if field in day["unreadable"]:
            if not public:
                parts.append(f'<h2>{label}</h2><p class="text muted">{UNREADABLE}</p>')
        elif day[field].strip():
            parts.append(f'<h2>{label}</h2><p class="text">{_e(day[field])}</p>')
    return "\n".join(parts)


def _photo_list(day: dict, public: bool, prefix: str = "", limit: int | None = None,
                skip: frozenset = frozenset()) -> str:
    items = []
    for name in _images(day, public, skip)[:limit]:
        src = prefix + urllib.parse.quote(name)
        note = f'<span class="muted">{NO_HEIC}</span>' if Path(name).suffix.lower() in photos.HEIC else ""
        items.append(f'<a href="{src}"><img src="{src}" alt="" loading="lazy"></a>{note}')
    return f'<div class="photos">{"".join(items)}</div>' if items else ""


def _mood(day: dict) -> str:
    if not day["mood"] and not day["note"].strip():
        return ""
    return f'<p class="mood">{_e(day["mood"])} {_e(day["note"])}</p>'


def neighbours(days: list[str], date: str) -> tuple[str | None, str | None]:
    """days 由舊到新；回 date 之前、之後最近的一天（date 自己不算）。"""
    i, j = bisect.bisect_left(days, date), bisect.bisect_right(days, date)
    return (days[i - 1] if i > 0 else None), (days[j] if j < len(days) else None)


def render_day(root: Path, date: str, *, public: bool = False, skip: frozenset = frozenset(),
               days: list[str] | None = None) -> str:
    """一天的頁。days 是有內容（公開版：公開）的日子，算前後一天用；一次產生很多頁時由呼叫的一方掃一次傳進來。"""
    d = diary.parse_date(date)
    day = diary.read_day(root, date)
    body = [f'<nav class="crumbs"><a href="../../../index.html">綜合</a> › <a href="../../index.html">{d.year}</a> › '
            f'<a href="../index.html">{d.month} 月</a></nav>', f"<h1>{_long_date(date)}</h1>"]
    content = _mood(day) + _fields(day, public) + _photo_list(day, public, skip=skip)
    body.append(content or f'<p class="muted">{EMPTY_DAY}</p>')
    before, after = neighbours(diary.all_days(root, public_only=public) if days is None else days, date)
    prev_link = f'<a href="../../../{_day_path(before)}/index.html">‹ {before}</a>' if before else "<span></span>"
    next_link = f'<a href="../../../{_day_path(after)}/index.html">{after} ›</a>' if after else "<span></span>"
    body.append(f'<nav class="pager">{prev_link}{next_link}</nav>')
    return _page(_long_date(date), "\n".join(body), public)


def _shift(y: int, m: int, step: int) -> tuple[int, int]:
    total = y * 12 + (m - 1) + step
    return total // 12, total % 12 + 1


def _month_href(here: tuple[int, int], there: tuple[int, int]) -> str:
    return f"../{there[1]:02d}/index.html" if here[0] == there[0] else f"../../{there[0]:04d}/{there[1]:02d}/index.html"


def _cut(text: str) -> str:
    return text if len(text) <= CELL_CHARS else text[:CELL_CHARS] + "…"


def render_month(root: Path, ym: str, *, public: bool = False) -> str:
    y, m = diary.parse_ym(ym)
    summary = diary.month_summary(root, ym, public_only=public)
    rows = []
    for week in calendar.Calendar(firstweekday=6).monthdayscalendar(y, m):
        cells = []
        for n in week:
            info = summary.get(f"{n:02d}")
            if n == 0:
                cells.append('<td class="empty"></td>')
            elif info is None:
                cells.append(f'<td class="day"><span class="n">{n}</span></td>')
            else:
                extra = (f' <span class="mood">{_e(info["mood"])}</span>' if info["mood"] else "") + (
                    f'<span class="first">{_e(_cut(info["first"]))}</span>' if info["first"] else "") + (
                    " 🖼" if info["images"] else "")
                cells.append(f'<td class="day has"><a href="{n:02d}/index.html"><span class="n">{n}</span>{extra}</a></td>')
        rows.append(f"<tr>{''.join(cells)}</tr>")
    pager = []
    for step, label in ((-1, "‹ 上一個月"), (1, "下一個月 ›")):
        there = _shift(y, m, step)
        has = diary.month_summary(root, f"{there[0]:04d}-{there[1]:02d}", public_only=public)
        pager.append(f'<a href="{_month_href((y, m), there)}">{label}</a>' if has else f'<span class="muted">{label}</span>')
    head = "".join(f"<th>{w}</th>" for w in WEEKDAYS)
    body = (f'<nav class="crumbs"><a href="../../index.html">綜合</a> › <a href="../index.html">{y}</a></nav>'
            f"<h1>{y} 年 {m} 月</h1>\n<table class=\"month\"><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}"
            f'</tbody></table>\n<nav class="pager">{pager[0]}{pager[1]}</nav>')
    return _page(f"{y} 年 {m} 月", body, public)


def render_year(root: Path, y: str, *, public: bool = False) -> str:
    year = diary.parse_year(y)
    blocks = []
    for m in range(1, 13):
        summary = diary.month_summary(root, f"{year:04d}-{m:02d}", public_only=public)
        title = f'<a href="{m:02d}/index.html">{m} 月</a>' if summary else f"{m} 月"
        rows = []
        for week in calendar.Calendar(firstweekday=6).monthdayscalendar(year, m):
            cells = []
            for n in week:
                info = summary.get(f"{n:02d}") if n else None
                if info is not None:
                    cells.append(f'<td><a href="{m:02d}/{n:02d}/index.html">{_e(info["mood"]) or "·"}</a></td>')
                else:
                    cells.append(f"<td>{n or ''}</td>")
            rows.append(f"<tr>{''.join(cells)}</tr>")
        head = "".join(f"<th>{w}</th>" for w in WEEKDAYS)
        blocks.append(f'<div><h2>{title}</h2><table class="mini"><thead><tr>{head}</tr></thead>'
                      f"<tbody>{''.join(rows)}</tbody></table></div>")
    body = (f'<nav class="crumbs"><a href="../index.html">綜合</a></nav><h1>{year} 年</h1>\n'
            f'<div class="months">{"".join(blocks)}</div>')
    return _page(f"{year} 年", body, public)


def render_index(root: Path, *, public: bool = False, skip: frozenset = frozenset(),
                 days: list[str] | None = None) -> str:
    days = diary.all_days(root, public_only=public) if days is None else days
    articles = []
    for date in reversed(days[-RECENT:]):
        day = diary.read_day(root, date)
        mood = f" {_e(day['mood'])}" if day["mood"] else ""
        note = f'<p class="mood">{_e(day["note"])}</p>' if day["note"].strip() else ""
        articles.append(f'<article><h2><a href="{_day_path(date)}/index.html">{_long_date(date)}</a>{mood}</h2>{note}'
                        f"{_fields(day, public)}{_photo_list(day, public, _day_path(date) + '/', RECENT_IMAGES, skip)}</article>")
    years: dict[str, dict[str, int]] = {}
    for date in days:
        months = years.setdefault(date[:4], {})
        months[date[5:7]] = months.get(date[5:7], 0) + 1
    entries = []
    for y in sorted(years, reverse=True):
        links = "、".join(f'<a href="{y}/{mm}/index.html">{int(mm)} 月（{n} 天）</a>' for mm, n in sorted(years[y].items()))
        entries.append(f'<li><a href="{y}/index.html">{y}</a>：{links}</li>')
    recent = "\n".join(articles) or f'<p class="muted">{EMPTY_DAY}</p>'
    body = (f'<h1>行事曆</h1>\n<section class="recent">{recent}</section>\n'
            f'<h2>每一年、每個月</h2><ul>{"".join(entries)}</ul>')
    return _page("行事曆", body, public)


def _out(root: Path, public: bool, out: Path | None) -> Path:
    return Path(out) if out is not None else (Path(root) / PUBLISH if public else Path(root))


def build_day(root: Path, date: str, *, public: bool = False, out: Path | None = None,
              skip: frozenset = frozenset(), days: list[str] | None = None) -> Path:
    path = _out(root, public, out) / _day_path(date) / "index.html"
    diary.write_text(path, render_day(root, date, public=public, skip=skip, days=days))
    return path


def build_month(root: Path, ym: str, *, public: bool = False, out: Path | None = None) -> Path:
    y, m = diary.parse_ym(ym)
    path = _out(root, public, out) / f"{y:04d}" / f"{m:02d}" / "index.html"
    diary.write_text(path, render_month(root, ym, public=public))
    return path


def build_year(root: Path, y: str, *, public: bool = False, out: Path | None = None) -> Path:
    path = _out(root, public, out) / f"{diary.parse_year(y):04d}" / "index.html"
    diary.write_text(path, render_year(root, y, public=public))
    return path


def build_index(root: Path, *, public: bool = False, out: Path | None = None, skip: frozenset = frozenset(),
                days: list[str] | None = None) -> Path:
    path = _out(root, public, out) / "index.html"
    diary.write_text(path, render_index(root, public=public, skip=skip, days=days))
    return path


def rebuild_after_save(root: Path, date: str) -> list[Path]:
    """存了 date 之後：那一天、前後有內容的日子、前一個／這個／下一個月（資料夾在才產）、這一年、綜合。"""
    root = Path(root)
    d = diary.parse_date(date)
    days = diary.all_days(root)  # 掃一次，傳給每一頁（不然每一頁各掃一次整個資料夾）
    before, after = neighbours(days, date)
    written = [build_day(root, x, days=days) for x in (date, before, after) if x]
    for step in (-1, 0, 1):
        y, m = _shift(d.year, d.month, step)
        if (root / f"{y:04d}" / f"{m:02d}").is_dir():
            written.append(build_month(root, f"{y:04d}-{m:02d}"))
    written += [build_year(root, f"{d.year:04d}"), build_index(root, days=days)]
    return written


def rebuild_all(root: Path) -> list[Path]:
    """所有有內容的日子、它們的月與年，加綜合；一天都沒有時只寫綜合。"""
    root = Path(root)
    days = diary.all_days(root)
    written = [build_day(root, date, days=days) for date in days]
    written += [build_month(root, ym) for ym in sorted({date[:7] for date in days})]
    written += [build_year(root, y) for y in sorted({date[:4] for date in days})]
    written.append(build_index(root, days=days))
    return written



def _publish_images(root: Path, out: Path, days: list[str], run, platform: str, problems: list[str]) -> tuple[set, set]:
    """每一天可以公開的圖：原圖比發佈/ 裡的新（或還沒有）才重做。回 (應有的檔, 處理不了的 (日期, 檔名))。"""
    wanted, skip = set(), set()
    for date in days:
        folder, target = diary.day_folder(root, date), out / _day_path(date)
        for name in diary.read_day(root, date)["images"]:
            suffix = Path(name).suffix.lower()
            if suffix in photos.HEIC:
                problems.append(NOT_PUBLISHED.format(date=date, name=name, why=HEIC_NOT_PUBLISHED))
                skip.add((date, name))
                continue
            src, dst = folder / name, target / name
            try:
                if not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
                    photos.public_copy(src, dst, run=run, platform=platform)
            except (ValueError, OSError) as exc:
                problems.append(NOT_PUBLISHED.format(date=date, name=name, why=exc))
                skip.add((date, name))
                continue
            wanted.add(dst)
    return wanted, skip


def _prune(out: Path, wanted: set) -> None:
    """發佈/ 裡不在應有清單上的檔刪掉（取消公開的那一天會消失），空了的資料夾也刪掉。"""
    for path in sorted(out.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_symlink() or path.is_file():
            if path not in wanted:
                path.unlink()
        elif path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def unpublish(root: Path) -> bool:
    """公開的日子是 0 天時拿掉整個 發佈/（裡面全是「發佈」自己產生的；別的檔 _prune 本來就會刪）。
    發佈/ 本來就不在回 False；是符號連結就只拿掉連結，不跟過去。"""
    out = Path(root) / PUBLISH
    if out.is_symlink():
        out.unlink()
        return True
    if not out.exists():
        return False
    shutil.rmtree(out)
    return True


def publish(root: Path, *, run=subprocess.run, platform: str = sys.platform, problems: list[str] | None = None) -> Path:
    """產生公開版 <資料夾>/發佈/（D92 的接口：回它的路徑；上傳之後接在這後面）。只有打開「公開」的日子；
    每次重寫所有網頁；圖片縮小、拿掉中繼資料，原圖比較新才重做；處理不了的圖每張一句進 problems，那張不出現在網頁上。"""
    root = Path(root)
    out = root / PUBLISH
    problems = [] if problems is None else problems
    days = diary.all_days(root, public_only=True)
    wanted, skip = _publish_images(root, out, days, run, platform, problems)
    frozen = frozenset(skip)
    wanted |= {build_day(root, date, public=True, skip=frozen, days=days) for date in days}
    wanted |= {build_month(root, ym, public=True) for ym in {date[:7] for date in days}}
    wanted |= {build_year(root, y, public=True) for y in {date[:4] for date in days}}
    wanted.add(build_index(root, public=True, skip=frozen, days=days))
    _prune(out, wanted)
    return out
