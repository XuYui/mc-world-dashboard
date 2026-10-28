"use strict";
// 皮肤 tab: a 3D preview of everyone's skin; after logging in with the game account (AuthMe
// password) a player can upload a new skin for themselves, preview it, and save it.
// The 3D viewer (vendor/skinview3d) is only loaded when the tab is first opened.

let skinState = null;        // /api/skins
let skinSel = null;          // uuid shown in the viewer
let skinPending = null;      // { dataUrl, b64, slim } chosen but not saved yet
let skinBusy = false;
let skinMsg = null;          // { text, bad }
let skinViewer = null;
let skinAnim = "walk";
let viewerLoading = null;

const ANIMS = [["walk", "走路"], ["wave", "挥手"], ["idle", "站着"]];

async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Requested-With": "mcdash" },
    body: JSON.stringify(body),
  });
  let d = {};
  try { d = await r.json(); } catch (e) {}
  return { ok: r.ok, status: r.status, data: d };
}

const skinURL = (p) => `skins/${p.uuid}.png?v=${p.v}`;
const selPlayer = () => skinState?.players.find((p) => p.uuid === skinSel) || null;
const kindText = (p) => (p.kind === "custom" ? "自定义皮肤" : "默认皮肤") + " · " + (p.slim ? "纤细" : "经典");

async function loadSkins() {
  try {
    skinState = await getJSON("api/skins");
  } catch (e) {
    return;
  }
  window.skinVersions = Object.fromEntries(skinState.players.map((p) => [p.uuid, p.v]));
  if (!skinSel || !selPlayer()) {
    const mine = skinState.players.find((p) => p.name === skinState.me);
    skinSel = (mine || skinState.players[0])?.uuid || null;
  }
  renderSkins();
  if (typeof renderStatus === "function") renderStatus();
}

// ---------- 3D viewer ----------

function loadViewerScript() {
  if (window.skinview3d) return Promise.resolve();
  if (!viewerLoading) {
    viewerLoading = new Promise((ok, fail) => {
      const s = document.createElement("script");
      s.src = "vendor/skinview3d/skinview3d.bundle.js";
      s.onload = ok;
      s.onerror = fail;
      document.head.appendChild(s);
    });
  }
  return viewerLoading;
}

function setAnimation() {
  if (!skinViewer) return;
  const A = window.skinview3d;
  skinViewer.animation = skinAnim === "walk" ? new A.WalkingAnimation() : skinAnim === "wave" ? new A.WaveAnimation() : new A.IdleAnimation();
}

function sizeViewer() {
  const box = $("#skinstage");
  if (!skinViewer || !box) return;
  const w = Math.max(200, Math.min(box.clientWidth - 8, 420));
  skinViewer.setSize(w, Math.round(w * (innerWidth <= 760 ? 0.95 : 1.15)));
}

async function showInViewer() {
  const p = selPlayer();
  const canvas = $("#skin3d");
  if (!p || !canvas || !$("#tab-skins").classList.contains("on")) return;
  try {
    await loadViewerScript();
  } catch (e) {
    setHTML($("#skincap"), `<span class="muted">3D 预览加载失败，刷新页面再试。</span>`);
    return;
  }
  if (!skinViewer || skinViewer.canvas !== canvas) {
    if (skinViewer) skinViewer.dispose();
    skinViewer = new window.skinview3d.SkinViewer({ canvas, width: 300, height: 345, zoom: 0.7 });
    skinViewer.controls.enablePan = false;
    skinViewer.autoRotate = true;
    skinViewer.autoRotateSpeed = 0.6;
    setAnimation();
    sizeViewer();
  }
  const src = skinPending && p.name === skinState.me ? skinPending.dataUrl : skinURL(p);
  const slim = skinPending && p.name === skinState.me ? skinPending.slim : p.slim;
  if (canvas.dataset.src !== src + slim) {
    canvas.dataset.src = src + slim;
    skinViewer.loadSkin(src, { model: slim ? "slim" : "default" });
  }
  skinViewer.renderPaused = !$("#tab-skins").classList.contains("on");
}

window.skinsTabShown = (shown) => {
  if (shown && !skinState) loadSkins();
  if (skinViewer) skinViewer.renderPaused = !shown;
  if (shown) { sizeViewer(); showInViewer(); }
};
window.addEventListener("resize", sizeViewer);

// ---------- rendering ----------

function renderSkins() {
  const tab = $("#tab-skins");
  if (!skinState) return;
  const p = selPlayer();
  if (!tab.querySelector("#skin3d")) {
    tab.innerHTML = `<div class="wrap">
      <h2>皮肤</h2>
      <div class="skingrid">
        <div class="card stagecard" id="skinstage">
          <div id="skincap" class="skincap"></div>
          <canvas id="skin3d" aria-label="皮肤 3D 预览"></canvas>
          <div class="stagebar"><div class="toggle" id="skinanim" role="group" aria-label="动作"></div>
            <a id="skindl" class="linkbtn" download>下载这张皮肤</a></div>
          <p class="muted stagehint">拖动可以转动，滚轮或双指缩放。</p>
        </div>
        <div class="skinside">
          <div class="card pickcard"><div class="skinpick" id="skinpick"></div></div>
          <div class="card editcard" id="skinedit"></div>
        </div>
      </div></div>`;
    tab._html = null;
    tab.addEventListener("click", onSkinClick);
    tab.addEventListener("change", onSkinChange);
    tab.addEventListener("submit", onSkinSubmit);
  }
  setHTML($("#skinanim"), ANIMS.map(([k, n]) => `<button type="button" data-anim="${k}" class="${skinAnim === k ? "on" : ""}">${n}</button>`).join(""));
  setHTML($("#skinpick"), skinState.players.map((q) => `
    <button type="button" class="person skinslot ${q.uuid === skinSel ? "sel" : ""}" data-pick="${esc(q.uuid)}" aria-label="${esc(q.name)}：${kindText(q)}" aria-pressed="${q.uuid === skinSel}">
      ${head(q, 30)}<div class="who"><span class="name">${esc(q.name)}${q.name === skinState.me ? " <span class=\"you\">（你）</span>" : ""}</span>
      <span class="sub">${kindText(q)}</span></div></button>`).join(""));
  const previewing = skinPending && p && p.name === skinState.me;
  setHTML($("#skincap"), p ? `<span class="nm">${esc(p.name)}</span>${previewing
    ? `<span class="tag live">预览中 · 还没保存</span>` : `<span class="tag">${kindText(p)}</span>`}` : "");
  const dl = $("#skindl");
  if (p) { dl.href = previewing ? skinPending.dataUrl : skinURL(p); dl.download = `${p.name}.png`; }
  renderSkinEditor(p);
  showInViewer();
}

function msgLine() {
  if (skinBusy) return `<div class="skinmsg">${esc(skinBusy)}</div>`;
  return skinMsg ? `<div class="skinmsg ${skinMsg.bad ? "bad" : "good"}">${esc(skinMsg.text)}</div>` : "";
}

function renderSkinEditor(p) {
  const s = skinState;
  const el = $("#skinedit");
  let html;
  if (!s.can_login) {
    const url = s.https_url ? s.https_url.replace(/\/?$/, "/") + "#skins" : "";
    html = `<h3 class="edh">更改皮肤</h3><p class="muted">现在可以预览所有人的皮肤。要更改，需要用游戏账号登录；为了保护密码，只能在加密（HTTPS）的地址登录${url
      ? `：<br><a href="${esc(url)}">${esc(url)}</a>` : "。"}</p>`;
  } else if (!s.me) {
    html = `<h3 class="edh">登录后更改自己的皮肤</h3>
      <form class="skinlogin" autocomplete="on">
        <label>账号<input name="name" autocomplete="username" required value="${esc(p?.name || "")}" spellcheck="false" autocapitalize="off"></label>
        <label>密码<input name="password" type="password" autocomplete="current-password" required></label>
        <button type="submit" class="mcbtn go" ${skinBusy ? "disabled" : ""}>登录</button>
      </form>
      <p class="muted small">密码就是进服务器时 <code>/login</code> 用的那个。不登录也可以随便预览。</p>${msgLine()}`;
  } else if (!p || p.name !== s.me) {
    const mine = s.players.find((q) => q.name === s.me);
    html = `<h3 class="edh">更改皮肤</h3><p class="muted">你登录的是 <b>${esc(s.me)}</b>，只能更改自己的皮肤；其他人的只能预览。</p>
      ${mine ? `<button type="button" class="mcbtn" data-pick="${esc(mine.uuid)}">看我的皮肤</button>` : ""}
      <p class="muted small">已登录为 ${esc(s.me)} · <button type="button" class="linkbtn" data-act="logout">退出登录</button></p>`;
  } else if (skinPending) {
    html = `<h3 class="edh">新皮肤预览</h3>
      <p class="muted">左边是换上之后的样子。手臂粗细不对的话在这里改：</p>
      <div class="toggle" role="group" aria-label="手臂">
        <button type="button" data-model="wide" class="${skinPending.slim ? "" : "on"}">经典（粗手臂）</button>
        <button type="button" data-model="slim" class="${skinPending.slim ? "on" : ""}">纤细（细手臂）</button></div>
      <div class="edbtns">
        <button type="button" class="mcbtn go" data-act="save" ${skinBusy ? "disabled" : ""}>保存皮肤</button>
        <button type="button" class="mcbtn" data-act="cancel" ${skinBusy ? "disabled" : ""}>取消</button></div>${msgLine()}`;
  } else {
    html = `<h3 class="edh">更改我的皮肤</h3>
      <label class="mcbtn go pickfile ${skinBusy ? "off" : ""}">选择皮肤图片…<input type="file" accept="image/png" hidden ${skinBusy ? "disabled" : ""}></label>
      <p class="muted small">64×64 的 PNG 皮肤文件。选好后先在左边预览，确认了再保存。</p>
      ${p.kind === "custom" ? `<button type="button" class="linkbtn" data-act="reset" ${skinBusy ? "disabled" : ""}>恢复默认皮肤</button>` : ""}
      ${msgLine()}
      <p class="muted small">已登录为 ${esc(s.me)} · <button type="button" class="linkbtn" data-act="logout">退出登录</button></p>`;
  }
  setHTML(el, html);
}

// ---------- actions ----------

function isSlim(img) {
  // slim skins leave the outer 1px column of the right arm (x 54-55, y 20-31) transparent
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d");
  g.drawImage(img, 0, 0);
  const d = g.getImageData(54, 20, 2, 12).data;
  for (let i = 3; i < d.length; i += 4) if (d[i] !== 0) return false;
  return true;
}

function chooseFile(file) {
  skinMsg = null;
  if (!file) return;
  if (file.size > 64 * 1024) { skinMsg = { text: "文件太大了，皮肤图片应该只有几 KB。", bad: true }; return renderSkins(); }
  const reader = new FileReader();
  reader.onload = () => {
    const dataUrl = reader.result;
    const img = new Image();
    img.onload = () => {
      if (img.naturalWidth !== 64 || img.naturalHeight !== 64) {
        skinMsg = { text: `皮肤必须是 64×64 像素（这张是 ${img.naturalWidth}×${img.naturalHeight}）。`, bad: true };
        return renderSkins();
      }
      skinPending = { dataUrl, b64: dataUrl.split(",")[1], slim: isSlim(img) };
      renderSkins();
    };
    img.onerror = () => { skinMsg = { text: "这张图片打不开，确认是 PNG 文件。", bad: true }; renderSkins(); };
    img.src = dataUrl;
  };
  reader.readAsDataURL(file);
}

function savedText(r) {
  if (!r.online) return "保存好了！下次进服就是新皮肤，其他人也都能看到。";
  return skinState.live_apply ? "保存好了！你在游戏里已经换上了，其他人马上就能看到。" : "保存好了！重新进一次服就能换上。";
}

async function saveSkin(reset) {
  if (skinBusy) return;
  skinBusy = reset ? "正在恢复默认皮肤…" : "正在签名并保存，大约要 5–20 秒…";
  skinMsg = null;
  renderSkins();
  const r = await postJSON("api/skin", reset ? { reset: true } : { png: skinPending.b64, slim: skinPending.slim }).catch(() => null);
  skinBusy = false;
  if (r && r.ok) {
    skinPending = null;
    skinMsg = { text: savedText(r.data) };
    skinState = r.data.state;
    window.skinVersions = Object.fromEntries(skinState.players.map((p) => [p.uuid, p.v]));
    if (typeof renderStatus === "function") renderStatus();
  } else {
    skinMsg = { text: r?.data?.error || "保存失败：连不上网站后台。", bad: true };
    if (r && r.status === 401) await loadSkins();
  }
  renderSkins();
}

async function onSkinSubmit(e) {
  if (!e.target.classList.contains("skinlogin")) return;
  e.preventDefault();
  const f = new FormData(e.target);
  skinBusy = "正在登录…";
  skinMsg = null;
  renderSkins();
  const r = await postJSON("api/login", { name: f.get("name"), password: f.get("password") }).catch(() => null);
  skinBusy = false;
  if (r && r.ok) {
    skinMsg = null;
    await loadSkins();
    const mine = skinState.players.find((p) => p.name === skinState.me);
    if (mine) skinSel = mine.uuid;
  } else {
    skinMsg = { text: r?.data?.error || "登录失败：连不上网站后台。", bad: true };
  }
  renderSkins();
}

function onSkinChange(e) {
  if (e.target.type === "file") {
    chooseFile(e.target.files[0]);
    e.target.value = "";
  }
}

async function onSkinClick(e) {
  const b = e.target.closest("[data-pick],[data-anim],[data-model],[data-act]");
  if (!b || b.disabled) return;
  if (b.dataset.pick) {
    skinSel = b.dataset.pick;
    if (!skinPending) skinMsg = null;
  } else if (b.dataset.anim) {
    skinAnim = b.dataset.anim;
    setAnimation();
  } else if (b.dataset.model && skinPending) {
    skinPending.slim = b.dataset.model === "slim";
  } else if (b.dataset.act === "cancel") {
    skinPending = null;
    skinMsg = null;
  } else if (b.dataset.act === "save") {
    return saveSkin(false);
  } else if (b.dataset.act === "reset") {
    if (confirm("恢复成游戏的默认皮肤？")) return saveSkin(true);
    return;
  } else if (b.dataset.act === "logout") {
    await postJSON("api/logout", {}).catch(() => null);
    skinPending = null;
    skinMsg = null;
    return loadSkins();
  }
  renderSkins();
}

// drop a PNG anywhere on the tab
document.addEventListener("dragover", (e) => { if ($("#tab-skins").classList.contains("on")) e.preventDefault(); });
document.addEventListener("drop", (e) => {
  if (!$("#tab-skins").classList.contains("on")) return;
  e.preventDefault();
  if (skinState?.me && selPlayer()?.name === skinState.me && !skinBusy) chooseFile(e.dataTransfer.files[0]);
});

loadSkins();
setInterval(() => { if (!skinBusy && !skinPending) loadSkins(); }, 60000);
