// 模組導覽列（D153）：頁面載入後由「頁面」模組注入（角色 page.top）。用法：(這個檔)(格子的清單)。
// 格子是 {k: "panel" | "parent" | "child", t: 字, i: 圖示的字, d: 滑鼠停著的說明}。
// 所有字都用 textContent 放，名稱裡有 < 也只是字。
(cells) => {
  if (!cells.length || !document.body || document.querySelector("iplot-nav") || document.querySelector('meta[name="iplot-nav"][content="off"]')) return;
  const bar = document.createElement("iplot-nav");
  bar.style.cssText = "all: initial; display: block; flex: none; position: sticky; top: 0; z-index: 2147483647";
  const box = window.getComputedStyle ? window.getComputedStyle(document.body).display : "";
  if (/flex|grid/.test(box)) bar.style.cssText += "; position: fixed; left: 0; right: 0";  // body 把內容置中（車車）：貼在視窗頂端，不跟著置中
  const root = bar.attachShadow({mode: "closed"});
  const style = document.createElement("style");
  style.textContent = `
    div { display: flex; align-items: center; gap: 2px; height: 32px; box-sizing: border-box; padding: 0 6px;
          overflow-x: auto; white-space: nowrap; background: #f3f3f5; color: #222; border-bottom: 1px solid #d4d4da;
          font: 13px/1 -apple-system, "Segoe UI", system-ui, sans-serif; }
    button { font: inherit; color: inherit; background: none; border: 0; border-radius: 6px; padding: 5px 8px; cursor: pointer; flex: none; }
    button:hover, button:focus-visible { background: rgba(128, 128, 128, 0.22); outline: none; }
    .parent { color: #b3261e; }
    i { width: 1px; height: 16px; margin: 0 4px; background: rgba(128, 128, 128, 0.4); flex: none; }
    @media (prefers-color-scheme: dark) {
      div { background: #2a2a2f; color: #eee; border-color: #444; }
      .parent { color: #ff8a80; }
    }`;
  const row = document.createElement("div");
  cells.forEach((cell, n) => {
    if (n && cells[n - 1].k !== cell.k) row.append(document.createElement("i"));
    const button = document.createElement("button");
    button.className = cell.k;
    button.title = cell.d;
    button.textContent = (cell.i ? cell.i + " " : "") + cell.t;
    button.addEventListener("click", () => {
      try { window.pywebview.api._iplot_nav(n); } catch (e) { /* 頁面的 api 還沒好：再按一次 */ }
    });
    row.append(button);
  });
  root.append(style, row);
  document.body.prepend(bar);
}
