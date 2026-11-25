// iPLoT 的面板。Python 那一頭是 ui/web.py：
//   Python → 頁面：iplot.init／show／log／report／ask／confirm／offer／busy（這個檔的最下面）
//   頁面 → Python：api().press(id) 這類呼叫，名字就是 ui/web.py 裡 Bridge 的方法
// 畫面上的字全部在 core/text.py，啟動時由 iplot.init 整份送進來放在 T；這個檔只用 key，不寫任何文字。
"use strict";

let T = {};                                                       // 畫面文字（core/text.py 的 T）
// 範圍、它的 JSON、選到的模組 id、正在執行的模組的名稱
const state = { scope: { crumbs: [], groups: [] }, shown: "", selected: null, busy: null };
let armed = null;            // 雙擊的第一下按在哪個模組上；第二下還在同一個模組上才算雙擊
const badIcons = new Set();  // 讀不出來的圖示檔（它的 data URI）：改用預設圖示，訊息區只說一次
const iplot = window.iplot = {};
const $ = (id) => document.getElementById(id);
const api = () => window.pywebview.api;
const find = (id) => state.scope.groups.flatMap((g) => g.modules).find((m) => m.id === id);

// 做一個元素：el("div", "tile selected", "文字")。文字一律用 textContent，模組印出來的東西不會被當成 HTML
function el(tag, className, text) {
  const e = document.createElement(tag);
  if (className) e.className = className;
  if (text != null) e.textContent = text;
  return e;
}

// ── 畫面：麵包屑、一組組圖示、狀態列 ──

function render() {
  const { crumbs, groups } = state.scope;
  const bar = $("crumbs");
  bar.replaceChildren();
  crumbs.forEach((name, i) => {
    const last = i === crumbs.length - 1;
    if (i) bar.append(el("span", "sep", "▸"));
    const b = el("button", last ? "here" : "", name);
    b.type = "button";
    if (!last) b.onclick = () => api().back(i);
    bar.append(b);
  });
  $("area").replaceChildren(...groups.map(groupEl));
  renderStatus();
}

function groupEl(g) {
  const section = el("section", "group");
  const head = el("div", "ghead");
  head.append(el("i", "dot " + g.level), el("span", "name", g.label), el("span", "path", g.path));
  section.append(head);
  if (!g.modules.length) section.append(el("div", "empty", g.note || T.empty_group));
  const tiles = el("div", "tiles");
  tiles.append(...g.modules.map(tileEl));
  if (g.note == null || g.level === "here") tiles.append(addTile(g));  // 其他根目錄讀不到時沒有地方可以建，不給 ＋；modules/ 被刪掉 create 會重建
  section.append(tiles);
  return section;
}

// 一個模組一格：單擊選取、雙擊執行、右鍵選單、▸ 進入下一層
function tileEl(m) {
  const tile = el("div", m.id === state.selected ? "tile selected" : "tile");
  tile.tabIndex = 0;
  tile.dataset.id = m.id;
  tile.title = m.error || m.description;
  const wrap = el("div", "iconwrap");
  wrap.append(iconEl(m));
  if (m.error) wrap.append(el("span", "badge warn", "!"));
  if (m.has_children) {
    const kids = el("button", "badge kids", "▸");
    kids.type = "button";
    kids.title = T.menu_enter;
    kids.onclick = (e) => { e.stopPropagation(); api().enter(m.id); };
    kids.ondblclick = (e) => e.stopPropagation();
    wrap.append(kids);
  }
  tile.append(wrap, el("div", "label", m.title));
  // 雙擊不用瀏覽器的 dblclick：第一下之後畫面可能換過（按 ▸ 進去、選單關掉），第二下落在別的東西上不能算
  tile.onclick = (e) => {
    select(m.id);
    if (e.detail >= 2 && armed === m.id) { armed = null; api().press(m.id); } else armed = m.id;
  };
  tile.onkeydown = (e) => { if (e.key === "Enter" && e.target === tile) api().press(m.id); };
  tile.oncontextmenu = (e) => {
    e.preventDefault(); select(m.id); openMenu(e.clientX, e.clientY, menuFor(m));
    api().menu(m.id);  // 模組提供的項目（改名、移到垃圾桶……）晚一點由 iplot.menu 補上（D159）
  };
  return tile;
}

// 圖示的來源（D65）：資料夾裡的圖檔 → ICON 常數 → 名字第一個字；底色的色相由資料夾名稱決定，每次都一樣
function iconEl(m) {
  if (m.icon && m.icon.file && !badIcons.has(m.icon.file)) {
    const img = el("img", "icon");
    img.src = m.icon.file;
    img.alt = "";
    img.draggable = false;
    img.onerror = () => {  // 檔案不是一張讀得出來的圖（壞了、下載到一半）：當作沒有圖示檔
      badIcons.add(m.icon.file);
      entry(T.icon_unusable.replace("{title}", m.title));
      img.replaceWith(iconEl(m));
    };
    return img;
  }
  const text = m.icon && m.icon.text;
  const icon = el("div", text ? "icon" : "icon letter", text || [...m.title][0].toUpperCase());
  icon.style.setProperty("--h", hue(m.name));
  return icon;
}

function hue(name) {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.codePointAt(0)) % 360;
  return h;
}

// 每組最後一格：虛線的 ＋
function addTile(g) {
  const tile = el("div", "tile");
  tile.tabIndex = 0;
  tile.title = T.ask_name;
  const wrap = el("div", "iconwrap");
  wrap.append(el("div", "icon add", "＋"));
  tile.append(wrap, el("div", "label", T.add_tile));
  const add = () => askName().then((name) => { if (name !== null) api().create(g.root, name); });
  tile.onclick = add;
  tile.onkeydown = (e) => { if (e.key === "Enter") add(); };
  return tile;
}

function select(id) {
  state.selected = id;
  for (const tile of document.querySelectorAll(".tile")) tile.classList.toggle("selected", tile.dataset.id === id);
  renderStatus();
}

// 狀態列：選到的模組的名稱與說明（檔案有語法錯誤時顯示錯誤）；沒選就顯示提示。有模組在執行時，右邊說是哪一個
function renderStatus() {
  const m = find(state.selected);
  const status = $("status");
  status.replaceChildren();
  if (m) status.append(el("b", "", m.title), el("span", m.error ? "bad" : "", m.error || m.description));
  else status.append(el("span", "", T.status_hint));
  if (state.busy) status.append(el("span", "busy", T.running.replace("{title}", state.busy)));
}

// ── 右鍵選單 ──

function menuFor(m) {
  const items = [[T.menu_run, () => api().press(m.id)]];
  if (m.has_children) items.push([T.menu_enter, () => api().enter(m.id)]);
  items.push(null,
    [T.menu_edit, () => api().action("edit", m.id)],
    [T.menu_reveal, () => api().action("reveal", m.id)],
    [T.menu_terminal, () => api().action("terminal", m.id)],
    null,
    [T.menu_add_child, () => askName().then((name) => { if (name !== null) api().add_child(m.id, name); })]);
  return items;
}

// items 的每一項是 [文字, 要做的事]；null 是分隔線
function openMenu(x, y, items) {
  const menu = $("menu");
  menu.replaceChildren();
  for (const item of items) {
    if (!item) { menu.append(el("hr")); continue; }
    const b = el("button", "", item[0]);
    b.type = "button";
    b.onclick = () => { closeMenu(); item[1](); };
    menu.append(b);
  }
  menu.hidden = false;
  const box = menu.getBoundingClientRect();  // 靠近視窗邊緣時往回收，不超出去
  menu.style.left = Math.max(8, Math.min(x, window.innerWidth - box.width - 8)) + "px";
  menu.style.top = Math.max(8, Math.min(y, window.innerHeight - box.height - 8)) + "px";
}

function closeMenu() { $("menu").hidden = true; }

// ── 面板內的對話框：一次只開一個，後來的排隊 ──
// kind 是 "ask"（有輸入框，回字串）或 "confirm"（只有兩顆鈕，回 true）；取消一律回 null。
// check(字串) 回一句話時，那句話顯示在輸入框下面、對話框不關；回空字串才算過。

let lastDialog = Promise.resolve();

function dialog(kind, title, initial = "", check = () => "") {
  lastDialog = lastDialog.then(() => new Promise((resolve) => {
    const scrim = $("scrim"), input = $("dlgInput"), hint = $("dlgHint"), heading = $("dlgTitle");
    const behind = [$("crumbs"), $("area"), $("drawer")];  // 對話框開著的時候，後面的東西不收鍵盤也不收滑鼠
    heading.textContent = title;
    input.hidden = kind !== "ask";
    input.value = initial;
    // offer（出錯了，要回報嗎？）：鈕換成「回報／不用」，多一個「這次執行期間不要再問」；答案是 {report, mute}
    const offer = kind === "offer", mute = $("dlgMute");
    $("dlgMuteRow").hidden = !offer;
    mute.checked = false;
    $("dlgOk").textContent = offer ? T.offer_yes : T.ok;
    $("dlgCancel").textContent = offer ? T.offer_no : T.cancel;
    hint.textContent = "";
    scrim.hidden = false;
    for (const part of behind) part.inert = true;
    heading.scrollTop = heading.scrollHeight;  // 模組先印了很多行才問：問題在最後一行，捲到看得到它
    if (kind === "ask") { input.focus(); input.select(); } else $("dlgOk").focus();
    const done = (value) => {
      scrim.hidden = true;
      for (const part of behind) part.inert = false;
      document.removeEventListener("keydown", key, true);
      resolve(value);
    };
    const ok = () => {
      const problem = kind === "ask" ? check(input.value) : "";
      if (problem) { hint.textContent = problem; input.focus(); }
      else done(offer ? { report: true, mute: mute.checked } : kind === "ask" ? input.value : true);
    };
    const cancel = () => done(offer ? { report: false, mute: mute.checked } : null);
    // 中文輸入法選字、取消選字時按的 Enter 與 Esc 是給輸入法的，不算（isComposing；Safari 的核心在那一下是 keyCode 229）
    const key = (e) => {
      if (e.isComposing || e.keyCode === 229 || (e.key !== "Escape" && e.key !== "Enter")) return;
      e.preventDefault();
      e.stopPropagation();  // 不讓這一下再傳到後面的格子上
      if (e.key === "Escape") cancel(); else ok();
    };
    // 雙擊的第二下不算：第一下已經答完這一題，下一題的對話框可能正好開在同一個位置
    $("dlgOk").onclick = (e) => { if (e.detail < 2) ok(); };
    $("dlgCancel").onclick = (e) => { if (e.detail < 2) cancel(); };
    document.addEventListener("keydown", key, true);
  }));
  return lastDialog;
}

// 新模組的名稱。規則跟 core/create.py 的 _bad_name 同一套：在對話框裡先擋，使用者不用重打整個名字；
// 這裡漏掉的，Python 那邊還會再擋一次，訊息區顯示同一句
const RESERVED = /^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$/i;
const badName = (n) => !n.trim() || n.startsWith(".") || /[. ]$/.test(n) || /[\\/:*?"<>|\u0000-\u001f]/.test(n)
  || RESERVED.test(n.split(".")[0]);
const askName = (title = T.ask_name, initial = "") => dialog("ask", title, initial, (n) => (badName(n) ? T.bad_name : ""));

// ── 訊息區：一行一條，自動捲到底 ──

const MAX_LOG = 2000;  // 最多留幾條，舊的丟掉

// error 有值時是一筆錯誤：先顯示白話那一句，「打開檔案」跳到出錯的那一行，「詳細」展開 traceback
function entry(text, error) {
  const log = $("log");
  const row = el("div", error ? "entry err" : "entry");
  const body = el("div", "t", text);
  row.append(el("i", "m"), body);
  if (error) {
    const acts = el("div", "acts");
    if (error.file) {
      const open = el("button", "btn-s", T.open_file);
      open.type = "button";
      open.onclick = () => api().open_error(error.id);
      acts.append(open);
    }
    if (error.traceback) {
      const tb = el("pre", "tb", error.traceback);
      tb.hidden = true;
      const more = el("button", "btn-s", T.details);
      more.type = "button";
      more.onclick = () => {
        tb.hidden = !tb.hidden;
        more.textContent = tb.hidden ? T.details : T.hide_details;
        row.scrollIntoView({ block: "nearest" });
      };
      acts.append(more);
      body.append(tb);
    }
    if (error.reportable) {  // 有「回報與討論」模組才有（D110）；按一次就變灰，不會排好幾個預覽頁
      const report = el("button", "btn-s", T.report_issue);
      report.type = "button";
      report.onclick = () => { report.disabled = true; api().report_error(error.id); };
      acts.append(report);
    }
    row.append(acts);
  }
  log.append(row);
  while (log.childElementCount > MAX_LOG) log.firstElementChild.remove();
  log.scrollTop = log.scrollHeight;
}

// ── 滑鼠與鍵盤 ──

document.addEventListener("click", (e) => {
  if (!e.target.closest(".menu, .scrim")) closeMenu();  // 第一次右鍵問「要允許嗎？」：按對話框不關選單，項目晚一點補上
  if (!e.target.closest(".tile, .menu, .scrim")) select(null);  // 點空白的地方：取消選取
});
// 雙擊的第一下如果不是按在模組那一格上（按的是 ▸、選單、別的地方），就不算數。在格子自己的 click 之前先看
document.addEventListener("click", (e) => {
  const tile = e.target.closest(".tile");
  if (!tile || tile.dataset.id !== armed || e.target.closest(".badge")) armed = null;
}, true);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });
document.addEventListener("contextmenu", (e) => { if (!e.target.closest(".tile")) { e.preventDefault(); closeMenu(); } });
$("area").addEventListener("scroll", closeMenu);
window.addEventListener("blur", closeMenu);
// 視窗取得焦點就重掃：在檔案總管新增、刪掉、改了模組，點回來就看得到（D11）
window.addEventListener("pywebviewready", () => window.addEventListener("focus", () => api().rescan()));

// ── Python 呼叫進來的八個入口（ui/web.py 的 WebPanel） ──

// 啟動時第一個收到：畫面文字、版本、是不是安全模式
iplot.init = (data) => {
  T = data.text;
  document.title = T.title.replace("{version}", data.version) + (data.safe ? T.safe_mode : "");
  $("dlgOk").textContent = T.ok;
  $("dlgCancel").textContent = T.cancel;
  $("dlgMuteText").textContent = T.offer_mute;
  render();
};

// 整個重畫。內容跟畫面上的一樣就不動：視窗取得焦點時的重掃不會打斷正在進行的雙擊
iplot.show = (scope) => {
  const text = JSON.stringify(scope);
  if (text === state.shown) return;
  state.scope = scope;
  state.shown = text;
  if (!find(state.selected)) state.selected = null;
  closeMenu();
  render();
};

iplot.log = (text) => { entry(text); };

// 右鍵選單上模組提供的項目：選單還開著、而且還是同一格才補上；按了送回第幾項
iplot.menu = (id, labels) => {
  const menu = $("menu"), m = find(id);
  if (menu.hidden || !m || state.selected !== id || !labels.length) return;
  openMenu(parseFloat(menu.style.left), parseFloat(menu.style.top),
    [...menuFor(m), null, ...labels.map((label, i) => [label, () => api().menu_pick(i)])]);
};

// error 的欄位見 ui/web.py 的 error_json；id 與 reportable 是 WebPanel.report 加的；sentence 是白話那一句
iplot.report = (error) => {
  if (error.source === "core") iplot.busy(null);  // 核心自己出錯時不一定來得及說「跑完了」
  entry(error.sentence, error);
};

// 模組開始執行時送它的名稱，結束時送 null。很快就跑完的不顯示，免得狀態列一直閃
let busyTimer = 0;
iplot.busy = (title) => {
  clearTimeout(busyTimer);
  if (title === null) { state.busy = null; renderStatus(); }
  else busyTimer = setTimeout(() => { state.busy = title; renderStatus(); }, 250);
};

// 問一個字串（模組的 input() 也是這個）；答案用 api().answer(編號, 字串或 null) 送回去
iplot.ask = (id, prompt, initial) => { dialog("ask", prompt, initial).then((value) => api().answer(id, value)); };

// 問「確定／取消」；送回 true 或 null
iplot.confirm = (id, prompt) => { dialog("confirm", prompt).then((value) => api().answer(id, value)); };

// 出錯了，要回報嗎（D150）；送回 {report, mute}
iplot.offer = (id, prompt) => { dialog("offer", prompt).then((value) => api().answer(id, value)); };
