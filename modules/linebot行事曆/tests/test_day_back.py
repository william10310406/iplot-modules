"""日檢視的返回鍵（0.3.1）：點進某一天之後，日期標題上方有「‹ 回到 N 月」，按了回月曆（跟上面的「月」同一條路 go("month")）。
page.html 在瀏覽器裡跑，這裡只釘住程式的寫法：按鈕在、文字有月份、呼叫的是 go("month")、先於日期標題、不用 innerHTML。"""

import re

import iplot

PAGE = (iplot.HERE / "page.html").read_text(encoding="utf-8")
SHOW_DAY = PAGE[PAGE.index("async function showDay()"):]
SHOW_DAY = SHOW_DAY[:SHOW_DAY.index("\n}\n")]


def test_the_day_view_has_a_back_to_month_button_that_goes_to_the_month():
    assert 'el("button", "backmonth", "‹ 回到 " + (cur.getMonth() + 1) + " 月")' in SHOW_DAY
    assert re.search(r'back\.addEventListener\("click", \(\) => go\("month"\)\)', SHOW_DAY)


def test_the_button_sits_above_the_date_heading_and_is_a_plain_button():
    assert SHOW_DAY.index('back.type = "button"') < SHOW_DAY.index("box.append(back, el(\"h2\"")


def test_the_top_bar_month_button_is_still_there_and_goes_the_same_way():
    assert '<button id="vMonth">月</button>' in PAGE
    assert '$("vMonth").addEventListener("click", () => go("month"))' in PAGE


def test_going_back_keeps_the_day_that_was_open_in_that_month():
    """go("month") 沒有傳日期：cur 還是那一天，畫出來的就是那一天所在的月；離開日檢視前 go 先存、再把 day 清掉。"""
    go = PAGE[PAGE.index("async function go("):PAGE.index("async function showMonth()")]
    assert "if (!(await saveDay())) return;" in go and 'if (view === "day" && v !== "day") day = null;' in go
    assert "if (date) cur = date;" in go
