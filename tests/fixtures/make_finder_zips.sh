#!/bin/sh
# Finder 的「壓縮」＝ `ditto -c -k --sequesterRsrc --keepParent`；檔名是 UTF-8 卻不標旗標。
# 用 zipfile 造的會自動標 UTF-8，測試會過、線上會退件，所以要真的壓。只能在 Mac 上跑。
set -eu
OUT="$(cd "$(dirname "$0")" && pwd)"
T="$(mktemp -d)"
cd "$T"
mkdir 整理桌面 && cd 整理桌面
printf '"""把桌面上的截圖收起來。"""\nICON = "🧹"\ndef run(app):\n    app.log("收好了")\n' > iplot.py
printf 'x = 1\n' > 小工具.py
mkdir 資料 .history
printf '說明\n' > 資料/說明.txt
printf 'old\n' > .history/20261019-iplot.py
printf 'x' > .DS_Store
ln -s iplot.py 捷徑
touch "$(printf 'Icon\r')"
xattr -w com.example.iplot 測試 小工具.py
cd "$T" && ditto -c -k --sequesterRsrc --keepParent 整理桌面 "$OUT/finder-整理桌面.zip"
mkdir 外層 && cp -R 整理桌面 外層/ && ditto -c -k --sequesterRsrc --keepParent 外層 "$OUT/finder-外層.zip"  # 依任務 0 探針結果：#1、#2 就是外面多包一層
NFD="$(python3 -c 'import unicodedata; print(unicodedata.normalize("NFD", "ガイド"))')"
mkdir "$NFD" && printf '"""NFD 的名字。"""\n' > "$NFD/iplot.py"
ditto -c -k --sequesterRsrc --keepParent "$NFD" "$OUT/finder-nfd.zip"
rm -rf "$T"
