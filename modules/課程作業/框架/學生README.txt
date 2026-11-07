{code} 作業

這個資料夾裡有：
  {file}  作業本身，要改的是這個檔
  coursework.py  讓作業跑起來的程式，不用改
  {code}Space  作業用的資料（可能是空的）
  README.txt  這份說明

下面縮排的行都是要打的指令，每個指令單獨一行；整行複製、貼到終端機、按 Enter。

== macOS ==

第 1 步：裝 Python（只要做一次）
到 https://www.python.org/downloads/ 下載 macOS 的安裝程式（Python 3.10 以上），雙擊照著裝好。
已經裝過 python.org 的 Python 3.10 以上就跳過這一步。

第 2 步：打開「終端機」，進到這個資料夾
用 Spotlight（按 ⌘ 加空白鍵）找「終端機」打開。打 cd 再打一個空格（先不要按 Enter），
把這個 {code} 資料夾從 Finder 拖進終端機的視窗，再按 Enter。
之後每次重新打開終端機，都要先做這一步。

第 3 步：確認 Python 版本

    {version_check}

要看到 Python 3.10 以上。如果看到 Python 3.9，或跳出「安裝命令列開發者工具」的框（按「取消」），
代表終端機還沒認到剛裝的 Python：把終端機整個關掉（⌘Q）再重開，回到第 2 步。

第 4 步：建 .venv（只要做一次）
作業用到的套件會裝在這個資料夾裡的 .venv，不會裝進電腦本身的 Python。

    {make_venv}

第 5 步：跑作業

    {run}

第一次跑會先裝作業用到的套件，要等幾分鐘。接著會列出可以跑的 case：打號碼、按 Enter，就會開視窗。
關掉一個視窗才會出現下一個。

改作業：用文字編輯器打開 {file}，改「# ── 從這裡開始是作業 ──」和「# ── 以下不用改 ──」兩行中間的部分，存檔，再做一次第 5 步。

== Windows（未經實機驗證） ==

第 0 步：TronClass 下載的 zip 要先在檔案總管按右鍵 →「全部解壓縮」，之後的每一步都在解開後的資料夾裡做；不能在 zip 裡面直接跑。
第 1 步：到 https://www.python.org/downloads/ 下載 Windows 的安裝程式（Python 3.10 以上），照著裝好。
第 2 步：在檔案總管打開解開後的 {code} 資料夾，在上面的網址列打 cmd、按 Enter，會開一個已經在這個資料夾裡的命令提示字元。
第 3 步：確認 Python 版本

    {win_version_check}

要看到 Python 3.10 以上。

第 4 步：建 .venv（只要做一次）

    {win_make_venv}

第 5 步：跑作業

    {win_run}

改作業的方法跟 macOS 一樣：改「# ── 從這裡開始是作業 ──」和「# ── 以下不用改 ──」兩行中間的部分，存檔，再做一次第 5 步。

== 出問題的時候 ==

- 看到「這份作業要 Python 3.10 以上」：回到第 3 步，確認 Python 版本。
- 第一次跑時裝套件失敗（多半是網路）：確定有網路，再做一次第 5 步。
- 看到「.venv 是用舊的 Python 建的」：確認第 3 步通過後，打下面這行重建，再做第 5 步。
      {remake_venv}
  Windows 的話打：
      {win_remake_venv}

== 交作業 ==

只交 {file}。coursework.py、{code}Space、.venv 都不用交。
