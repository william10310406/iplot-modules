# iplot-modules

## 這是什麼

iPLoT 工作坊裡的模組，都從這裡來。

誰都能上傳自己寫的模組。有 GitHub 帳號就行。

**這一版沒有人審查。** 上傳的東西誰都看得到、誰都能下載執行。iPLoT 的工作坊頁面最上面會有一行提醒（寫在 `notice.txt`）。裝進來的模組第一次執行前，iPLoT 會先問；按確定之前，先看一眼程式碼。

iPLoT 核心的更新不在這裡。核心在 `iplot-workshop`，上傳碰不到它。

## 怎麼上傳

1. 在 Finder 對著模組的資料夾按右鍵，選「壓縮」。
2. 打開[「上傳模組」表單](https://github.com/william10310406/iplot-modules/issues/new?template=%E4%B8%8A%E5%82%B3%E6%A8%A1%E7%B5%84.yml)，把 zip 拖進去，勾「我知道…」，送出。
3. 一兩分鐘後，看那個 issue 的回覆。收到了就會寫「收到了」，issue 關掉；沒收就會用一句話說哪裡不對。改好再開一個新的。

再過幾分鐘，在 iPLoT 按「工作坊」，清單上就有你的模組，底下一行寫上傳者。

注意：

- zip 裡的每個檔都會公開，包括 Finder 裡看不到的檔（按 ⌘⇧. 顯示）。
- `.venv`、`.history`、模組自己存的資料，先拿掉再壓。
- 傳上去就進了 git 歷史。之後下架，歷史裡還是拿不掉。

## 規矩

- 名字歸第一次傳它的帳號。機器人認的是帳號的數字 id，改了帳號名也認得。
- 大小寫要跟第一次傳的一樣。
- 作業系統、更新、工作坊這三個名字，誰都不能傳。
- 隨附模組的名字，先登記給研究助理。
- 看起來一樣的寫法也不收：大小寫、相容字、看不見的字、不同文字的字母混用。
- `iplot.py` 的 `TITLE` 也算名字，同樣的規則。
- 版本照 `CHANGELOG.md` 最上面那一節。沒有 `CHANGELOG.md`，版本自動加一。
- 上限：
  - zip 最大 25 MB，解開最多 100 MB。
  - 最多 2000 個檔；zip 的條目最多 20000 條。
  - `iplot.py` 最大 1 MB。
  - 說明最多 500 字；這一版改了什麼最多 1000 字；ICON 最多 16 字。
  - 每個帳號 24 小時內最多 10 份，最多 20 個名字。
  - `modules/` 到 800 MB 之後，不收新的名字。
- 機器人只讀不執行：上傳的東西只會被解壓、檢查語法、寫進 repo，一行都不會跑。

## 沒收的原因

機器人沒收的時候，會在 issue 裡說下面的其中一句。〈〉裡是機器人填進去的字。

| 情況 | 機器人的那一句 |
|---|---|
| 不是一般帳號 | 只收一般帳號上傳的。 |
| 帳號已經不在 | 上傳的帳號已經不在了，不收。 |
| 沒有 zip | 沒有找到 zip：把模組資料夾壓成 .zip，拖進「模組的 zip」那一格。 |
| 不只一個 zip | 一次只能傳一個 zip。 |
| 沒有勾確認 | 沒有勾「我知道…」：用表單重新開一個，勾了再送出。 |
| 下載不到附件 | 下載不到附件（〈reason〉）。等一下再開一個新的。 |
| zip 太大 | zip 超過 25 MB。 |
| 不是 zip | 附件不是 zip。 |
| zip 打不開或壞了 | 這個 zip 打不開或壞了（〈kind〉）：用 Finder 重新壓縮一次，不要加密碼。 |
| 形狀不對 | zip 裡要剛好是一個資料夾（模組的資料夾），裡面有 iplot.py（檔名全小寫）：在 Finder 對著那個資料夾按右鍵「壓縮」。 |
| 路徑不能用 | zip 裡有不能用的路徑：〈path〉（..、絕對路徑、反斜線、控制字元、Windows 不能用的字元與保留字、結尾是 . 或空白、空的一段、重複或只差大小寫、檔跟資料夾同名）。 |
| 檔名不是 UTF-8 | zip 裡的檔名不是 UTF-8（舊的 Windows 內建壓縮會這樣）：在 Mac 上用 Finder 壓縮，或用 7-Zip。 |
| 解開太大 | 解開之後超過 100 MB。 |
| 檔太多 | 解開之後超過 2000 個檔。 |
| 條目太多 | zip 裡的條目太多（超過 20000 條）。 |
| 名稱不合規則 | 名稱不能是空白、以 . 開頭、結尾是 . 或空白、含 / \ : * ? " < > \|，也不能是 CON、NUL 這類 Windows 保留字（模組要能複製到任何系統） |
| 名稱有看不見的字 | 名稱裡有看不見的字元、特別的空白，或混用了不同文字的字母：用一般的字重新取名。 |
| 名稱太像別人的 | 「〈name〉」跟「〈other〉」太像：換一個名字。 |
| 保留的名稱 | 「〈name〉」是 iPLoT 自己要用的模組，不能上傳。 |
| 已下架 | 「〈name〉」已經下架；有問題找研究助理（README 的聯絡方式）。 |
| 名字是別人的 | 「〈name〉」已經是別的帳號（〈owner〉）的模組；換一個名字（改資料夾名稱）再傳。 |
| TITLE 是別人的 | iplot.py 的 TITLE「〈title〉」是別人的、保留的，或太像別人的名字：拿掉 TITLE，或改成自己的名稱。 |
| 大小寫不一樣 | 大小寫要跟第一次一樣：這個名字第一次傳的是「〈first〉」。 |
| 24 小時內傳太多份 | 這個帳號 24 小時內已經傳了 〈n〉 份：明天再傳，或找研究助理。 |
| 名字太多 | 這個帳號已經有 〈n〉 個名字：明天再傳，或找研究助理。 |
| 空間快滿了 | 工作坊的空間快滿了，研究助理處理中；暫時不收新的名字。 |
| 語法錯誤 | iplot.py 第 〈line〉 行：〈message〉。 |
| 只有 3.10 報錯的語法 | iplot.py 第 〈line〉 行：〈message〉。iPLoT 要能在 Python 3.10 跑。 |
| iplot.py 不是 UTF-8 | iplot.py 不是 UTF-8：用 UTF-8 存檔再傳。 |
| iplot.py 解析不了 | iplot.py 解析不了（太複雜）。 |
| CHANGELOG 讀不出 | CHANGELOG.md 讀不出最上面那一版：〈reason〉。 |
| 版本沒有比較新 | CHANGELOG.md 最上面那一節的版本 〈v〉 不比現在的 〈cur〉 新：把版本號加大再傳。 |
| push 被擋 | 推不上去（〈reason〉）：多半是檔案裡有密碼或金鑰，拿掉再傳。 |
| push 不成功 | 這次沒收成，一小時內會自動再試；一天後還是這樣，在這裡留言。 |
| 機器人出錯 | 機器人處理不了這份上傳，研究助理會看。 |
| iplot.py 太大 | iplot.py 超過 1 MB。 |
| 版本寫法不對 | 版本不是 1.2.0 這種寫法：〈version〉。 |
| 寫不進 repo | 這份 zip 寫不進 repo。 |

## 下架、轉名字、警告（研究助理做）

- 下架：刪掉 `modules/<名稱>/`，在 `registry.json` 那一筆加 `"removed": true`，push。
- 轉名字：改那一筆的 `owner_id`。
- 警告：把 `warning` 寫在那一筆，清單上會顯示。
- `notice.txt` 改了字，清單最上面那一行就換掉。
- 有 issue 標了「卡住」：看 Actions 的紀錄。

有問題找研究助理：GitHub [@william10310406](https://github.com/william10310406)。

## 給改機器人的人

`tools/` 裡：

- `receive.py`：收上傳。讀 issue、下載 zip、檢查、寫進 repo、回覆。
- `zipcheck.py`：檢查 zip 的形狀、路徑、大小、檔名編碼。
- `source.py`：讀 `iplot.py` 與 `CHANGELOG.md`，只讀不執行。
- `registry.py`：`registry.json`，名字是誰的、版本、上限。
- `build.py`：照 registry 打固定的 zip，寫 `index.json` 與 `index.html`。
- `gh.py`：GitHub API 與下載附件（下載不帶 token）。
- `say.py`：機器人的每一句話。名稱、帳號名、路徑一律放進程式碼格式。
- `iplot_rules.py`：iPLoT 規則的抄本。

`tools/iplot_rules.py` 抄自 iPLoT。改了 iPLoT 的這幾處，要連這裡一起改：`_bad_name`、`T["bad_name"]`、`T["syntax_error"]`、`Meta`／`read_meta`、`changelog_notes`／`latest`、`_url`、`SKIP`、`NEEDED`、`_newer`、`read_listing`、`install` 的形狀檢查（就是 `tools/iplot_rules.py` 檔頭那張名單）。兩邊的 `tests/test_rules_table.py` 是同一張表。

跑測試：`python -m pytest -q`（要有 `python3.10`）。

Finder 的樣本怎麼重產：`tests/fixtures/make_finder_zips.sh`（要在 Mac 上跑）。

PR 只跑「測試」，不合併、不部署。fork 的 PR 一律要核可；核可之前先看有沒有動 `.github/`，有就不核可。
