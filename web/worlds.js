"use strict";
// 世界 tab: the server keeps several worlds on disk but runs only one at a time. Shows which one
// runs and who is on it; with the admin password the running world can be swapped for another.
// The status bar in app.js reads window.worldsState to say which world is running instead.

let worldsState = null;      // /api/worlds
let worldTarget = null;      // id picked for switching
let worldConfirm = null;     // { online, names } when players would be kicked
let worldBusy = false;
let worldMsg = null;         // { text, bad }

const STATE_TEXT = {
  active: "运行中", activating: "启动中", deactivating: "正在关闭", inactive: "已关闭", failed: "出错停止了",
};
const SWITCH_TEXT = {
  queued: "准备切换…", waiting: "每日备份进行中，备份完会自动切换…", stopping: "正在保存并关闭当前世界…",
  starting: "正在启动新世界…", started: "已启动", error: "切换出错",
};

async function loadWorlds() {
  try {
    worldsState = await getJSON("api/worlds");
  } catch (e) {
    return;
  }
  window.worldsState = worldsState;
  renderWorlds();
  if (typeof renderStatus === "function") renderStatus();
}

function worldTitle(id) {
  return worldsState?.worlds.find((w) => w.id === id)?.title || id;
}

// What the running world is doing right now, in words.
function runningLine(s) {
  if (s.switching && s.last) {
    const to = s.last.to ? `（→ ${esc(worldTitle(s.last.to))}）` : "";
    return `<div class="skinmsg">${esc(SWITCH_TEXT[s.last.state] || "切换中…")}${to}</div>`;
  }
  if (!s.running) return `<div class="skinmsg bad">现在没有世界在运行。</div>`;
  if (!s.ready) return `<div class="skinmsg">${esc(worldTitle(s.running))} 正在启动，模组服可能要一两分钟…</div>`;
  const p = s.ping;
  const who = p.online ? `${p.online} 人在线：${p.names.map(esc).join("、") || "…"}` : "没人在线";
  return `<div class="skinmsg good">${esc(worldTitle(s.running))} 已就绪 · ${who}</div>`;
}

function renderWorlds() {
  const tab = $("#tab-worlds");
  const s = worldsState;
  if (!s) return;
  if (!tab._wired) {
    tab._wired = true;
    tab.addEventListener("click", onWorldClick);
    tab.addEventListener("submit", onWorldSubmit);
  }
  const cards = s.worlds.map((w) => {
    const on = w.id === s.running;
    const st = on && !s.ready && w.state === "active" ? "启动中" : STATE_TEXT[w.state] || w.state;
    const pick = !on && s.enabled && !s.switching
      ? `<button type="button" class="mcbtn ${worldTarget === w.id ? "go" : ""}" data-world="${esc(w.id)}">切换到这个世界</button>` : "";
    return `<div class="card wcard ${on ? "on" : ""}">
      <div class="whead"><b>${esc(w.title)}</b><span class="chip ${on ? "ok" : ""}"><b>● ${esc(st)}</b></span></div>
      <div class="muted small">服务端：${esc(w.game || "")}</div>
      <div class="muted small">客户端：${esc(w.client || "")}</div>
      ${w.dashboard ? `<div class="muted small">地图、联机日志等页面记录的是这个世界。</div>` : ""}
      ${pick}</div>`;
  }).join("");

  let form = "";
  if (!s.enabled) {
    form = `<p class="muted small">还没有设置管理员密码，暂时只能查看。</p>`;
  } else if (worldTarget && !s.switching) {
    const from = s.running ? `关闭 <b>${esc(worldTitle(s.running))}</b>，然后` : "";
    const kick = worldConfirm
      ? `<p class="warnline">⚠ 现在有 ${worldConfirm.online} 人在线（${worldConfirm.names.map(esc).join("、")}），切换会把他们踢下线。确定吗？</p>` : "";
    form = `<div class="card"><p>将${from}启动 <b>${esc(worldTitle(worldTarget))}</b>。关闭前会自动存档。</p>${kick}
      <form class="skinlogin" id="worldform" autocomplete="off">
        <label>管理员密码<input name="password" type="password" autocomplete="current-password" required></label>
        <div class="edbtns">
          <button type="submit" class="mcbtn go" ${worldBusy ? "disabled" : ""}>${worldConfirm ? "仍然切换" : "确认切换"}</button>
          <button type="button" class="mcbtn" data-act="cancel">取消</button></div>
      </form></div>`;
  }
  const msg = worldMsg ? `<div class="skinmsg ${worldMsg.bad ? "bad" : "good"}">${esc(worldMsg.text)}</div>` : "";
  const err = s.error ? `<p class="muted small">⚠ 读取服务器状态出错：${esc(s.error)}</p>` : "";
  const html = `<div class="wrap"><h2>世界</h2>
    <p class="muted">服务器上存着几个世界，但内存只够同时开一个。地址都一样，换世界时用对应的客户端进。</p>
    ${runningLine(s)}${err}
    <div class="wgrid">${cards}</div>${form}${msg}</div>`;
  // keep a password being typed: only repaint the form when it is not on screen
  const typing = tab.querySelector("#worldform input[name=password]");
  if (typing && worldTarget && !s.switching) {
    const keep = typing.value;
    if (setHTML(tab, html)) {
      const again = tab.querySelector("#worldform input[name=password]");
      if (again) again.value = keep;
    }
  } else {
    setHTML(tab, html);
  }
}

function onWorldClick(e) {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.world) {
    worldTarget = b.dataset.world;
    worldConfirm = null;
    worldMsg = null;
    renderWorlds();
    $("#worldform input")?.focus();
  } else if (b.dataset.act === "cancel") {
    worldTarget = null;
    worldConfirm = null;
    renderWorlds();
  }
}

async function onWorldSubmit(e) {
  if (e.target.id !== "worldform") return;
  e.preventDefault();
  const password = new FormData(e.target).get("password");
  worldBusy = true;
  renderWorlds();
  const r = await postJSON("api/worlds/switch", { to: worldTarget, password, force: !!worldConfirm }).catch(() => null);
  worldBusy = false;
  if (r && r.ok) {
    worldMsg = { text: `开始切换到 ${worldTitle(worldTarget)}，这里会显示进度。` };
    worldTarget = null;
    worldConfirm = null;
  } else if (r && r.data.confirm) {
    worldConfirm = { online: r.data.online, names: r.data.names || [] };
  } else {
    worldMsg = { text: r?.data.error || "连不上网站后台，稍后再试。", bad: true };
  }
  await loadWorlds();
  renderWorlds();
}

loadWorlds();
// every 5 s while switching or while the tab is open, otherwise every 30 s
let worldTicks = 0;
setInterval(() => {
  const s = worldsState;
  const busy = s && (s.switching || (s.running && !s.ready));
  if (busy || $("#tab-worlds").classList.contains("on") || ++worldTicks % 6 === 0) loadWorlds();
}, 5000);
