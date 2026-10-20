"use strict";
// The map: our own Leaflet map over squaremap-layout tiles (tiles/<world>/<zoom>/<x>_<z>.png,
// 512 px, zoom 3 = 1 block per pixel). Any renderer that writes that layout can replace squaremap.
// Players and gravestones are our own layers, fed by the backend.

const TILE = 512, NATIVE_ZOOM = 3, MAX_ZOOM = NATIVE_ZOOM + 2;
const DRAG_GRACE = 3000;  // ms the view is left alone after the viewer drags while following
const WORLDS = { "minecraft:overworld": "minecraft_overworld", "minecraft:the_nether": "minecraft_the_nether", "minecraft:the_end": "minecraft_the_end" };

// Block (x, z) <-> LatLng: at zoom 3 one pixel is one block.
const CRS = L.extend({}, L.CRS.Simple, { transformation: new L.Transformation(1, 0, 1, 0) });
const toLatLng = (x, z) => L.latLng(z / 2 ** NATIVE_ZOOM, x / 2 ** NATIVE_ZOOM);
const toBlock = (ll) => ({ x: Math.floor(ll.lng * 2 ** NATIVE_ZOOM), z: Math.floor(ll.lat * 2 ** NATIVE_ZOOM) });

let mapDim = "minecraft:overworld";
const map = L.map("map", {
  crs: CRS, minZoom: 0, maxZoom: MAX_ZOOM, zoomSnap: 1, attributionControl: false, zoomControl: true,
  preferCanvas: false,
}).setView(toLatLng(0, 0), NATIVE_ZOOM);

const tiles = L.tileLayer("tiles/{world}/{z}/{x}_{y}.png", {
  world: WORLDS[mapDim], tileSize: TILE, minZoom: 0, maxZoom: MAX_ZOOM, maxNativeZoom: NATIVE_ZOOM,
  noWrap: true, keepBuffer: 1, className: "pixel",
  errorTileUrl: "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==",
}).addTo(map);
tiles.once("load", () => $("#maploading").classList.add("gone"));
setTimeout(() => $("#maploading").classList.add("gone"), 15000);

window.mapResized = () => setTimeout(() => map.invalidateSize(), 0);

// Tiles change as the world is explored: revalidate the visible ones every 2 minutes
// (unchanged tiles cost a 304) and swap in only those that really changed.
const tileTags = new Map();
async function refreshTiles() {
  if (document.hidden || map._animatingZoom) return;
  for (const t of Object.values(tiles._tiles || {})) {
    const img = t.el, src = img.dataset.src || img.src;
    if (!src || src.startsWith("data:")) continue;
    img.dataset.src = src;
    try {
      const r = await fetch(src, { cache: "no-cache" });
      if (!r.ok) continue;
      const tag = r.headers.get("ETag");
      if (tileTags.has(src) && tileTags.get(src) !== tag) img.src = URL.createObjectURL(await r.blob());
      tileTags.set(src, tag);
    } catch (e) {}
  }
}
setInterval(refreshTiles, 120000);

// ---------- coordinates under the cursor ----------

map.on("mousemove", (e) => {
  const b = toBlock(e.latlng);
  const el = $("#coords");
  el.classList.remove("gone");
  el.textContent = `X ${b.x}  Z ${b.z}`;
});
map.on("mouseout", () => $("#coords").classList.add("gone"));

// ---------- dimensions ----------

function setDimButton(dim) {
  document.querySelectorAll("#dims button").forEach((b) => b.classList.toggle("on", b.dataset.dim === dim));
}

function setDimension(dim) {
  if (dim === mapDim) return;
  mapDim = dim;
  setDimButton(dim);
  tiles.options.world = WORLDS[dim] || dim.replace(":", "_");
  tiles.redraw();
  drawGraves();
  drawPlayers(lastPlayers);
}

// Jump to a place (from the other tabs). Stops following unless keepFollow.
function showOnMap(opts, keepFollow = false) {
  if (!keepFollow) stopFollow();
  setDimension(opts.dim || "minecraft:overworld");
  openTab("map");
  window.mapResized();
  if (opts.x != null) map.setView(toLatLng(opts.x, opts.z), opts.zoom ?? map.getZoom());
}

document.querySelectorAll("#dims button").forEach((b) => b.addEventListener("click", () => {
  if (b.dataset.dim === mapDim) return;
  stopFollow();
  setDimension(b.dataset.dim);
  const spawn = b.dataset.dim === "minecraft:overworld" && data?.spawn ? data.spawn : [0, 0];
  map.setView(toLatLng(spawn[0], spawn[1]), NATIVE_ZOOM);
}));

window.mapDataChanged = () => {
  if (!map._centeredOnce && data?.spawn) {
    map._centeredOnce = true;
    map.setView(toLatLng(data.spawn[0], data.spawn[1]), NATIVE_ZOOM);
  }
};

// ---------- players ----------

const playerLayer = L.layerGroup().addTo(map);
const playerMarkers = new Map();
let lastPlayers = [];

function playerIcon(p) {
  return L.divIcon({
    className: "player-marker",
    html: `<img class="head" src="heads/${esc(p.uuid)}.png" alt="" width="24" height="24">`,
    iconSize: [24, 24], iconAnchor: [12, 12],
  });
}
const plate = (p) => `${esc(p.name)}<span class="plate-hp">❤ ${p.health}</span>`;

function drawPlayers(players) {
  lastPlayers = players;
  const here = players.filter((p) => p.world === mapDim);
  const seen = new Set();
  for (const p of here) {
    seen.add(p.uuid);
    let m = playerMarkers.get(p.uuid);
    if (!m) {
      m = L.marker(toLatLng(p.x, p.z), { icon: playerIcon(p), zIndexOffset: 1000 })
        .bindTooltip(plate(p), { permanent: true, direction: "top", offset: [0, -12], className: "plate" })
        .on("click", () => followPlayer(p.uuid));
      m.addTo(playerLayer);
      playerMarkers.set(p.uuid, m);
    } else {
      m.setLatLng(toLatLng(p.x, p.z));
      m.setTooltipContent(plate(p));
    }
  }
  for (const [id, m] of playerMarkers) {
    if (!seen.has(id)) {
      playerLayer.removeLayer(m);
      playerMarkers.delete(id);
    }
  }
}

// ---------- following a player ----------

let follow = null;  // { uuid, name }
let followPausedUntil = 0;
let followFirst = true;

function followPlayer(uuid) {
  const p = lastPlayers.find((x) => x.uuid === uuid);
  const name = p?.name || data?.players.find((x) => x.uuid === uuid)?.name || "";
  follow = { uuid, name };
  followFirst = true;
  followPausedUntil = 0;
  map.options.scrollWheelZoom = map.options.touchZoom = map.options.doubleClickZoom = "center";
  showFollowChip(`正在跟随 <b>${esc(name)}</b>`);
  if (p) setDimension(p.world);
  openTab("map");
  window.mapResized();
  followTick();
}

function stopFollow() {
  follow = null;
  map.options.scrollWheelZoom = map.options.touchZoom = map.options.doubleClickZoom = true;
  $("#follow").classList.add("gone");
}

function showFollowChip(html) {
  $("#follow span").innerHTML = html;
  $("#follow").classList.remove("gone");
}

function followTick() {
  if (!follow) return;
  const p = lastPlayers.find((x) => x.uuid === follow.uuid);
  if (!p) {
    showFollowChip(`<b>${esc(follow.name)}</b> 已下线`);
    follow = null;
    map.options.scrollWheelZoom = map.options.touchZoom = map.options.doubleClickZoom = true;
    return;
  }
  if (p.world !== mapDim) setDimension(p.world);  // went through a portal
  if (Date.now() < followPausedUntil) return;
  map.panTo(toLatLng(p.x, p.z), { animate: !followFirst, duration: 0.8 });
  followFirst = false;
}

map.on("dragstart", () => { if (follow) followPausedUntil = Infinity; });
map.on("dragend", () => { if (follow) followPausedUntil = Date.now() + DRAG_GRACE; });
$("#follow button").addEventListener("click", stopFollow);

window.mapLive = (players) => {
  drawPlayers(players);
  followTick();
};

// ---------- gravestones ----------

let graves = [];
let deathMode = null;  // null | "recent" | "all"
const graveLayer = L.layerGroup().addTo(map);

// 16x16 pixel-art gravestone, drawn here so no game texture is needed.
const GRAVE_ICON = (() => {
  const rows = ["................", "................", ".....######.....", "....#hhhhss#....", "...#hhhhhsss#...",
    "...#hhh##sss#...", "...#hh####ss#...", "...#hhh##sss#...", "...#hhh##sss#...", "...#hhhhhsss#...",
    "...#hhhhhsss#...", "...#hhhhhsss#...", "..##########dd..", ".gggggggggggggg.", ".dddddddddddddd.", "................"];
  const pal = { "#": "#2b2b2b", h: "#a0a0a0", s: "#6e6e6e", g: "#5e9c3a", d: "#6b4a2b" };
  const c = document.createElement("canvas");
  c.width = c.height = 16;
  const g = c.getContext("2d");
  rows.forEach((row, y) => [...row].forEach((ch, x) => {
    if (pal[ch]) { g.fillStyle = pal[ch]; g.fillRect(x, y, 1, 1); }
  }));
  return L.icon({ iconUrl: c.toDataURL(), iconSize: [20, 20], iconAnchor: [10, 18], className: "grave" });
})();

async function loadGraves() {
  try { graves = await getJSON("api/graves"); } catch (e) {}
  drawGraves();
}

function visibleGraves() {
  if (!deathMode) return [];
  let list = graves.filter((g) => g.where);
  if (deathMode === "recent") {
    const latest = {};
    for (const g of list) if (!latest[g.name] || latest[g.name].ts < g.ts) latest[g.name] = g;
    list = Object.values(latest);
  }
  return list;
}

function drawGraves() {
  graveLayer.clearLayers();
  for (const g of visibleGraves().filter((g) => g.where.dim === mapDim)) {
    const tip = `<b>${esc(g.name)}</b><br>${esc(g.text)}<br>${fmtDateTime(g.ts)} · (${g.where.pos.join(", ")})`;
    L.marker(toLatLng(g.where.pos[0], g.where.pos[2]), { icon: GRAVE_ICON }).bindTooltip(tip, { className: "plate", direction: "top", offset: [0, -16] }).addTo(graveLayer);
  }
  renderGraveList();
}

// With 最近死亡 on, list each player's latest death so it can be found even off-screen.
function renderGraveList() {
  const el = $("#gravelist");
  if (deathMode !== "recent") return el.classList.add("gone");
  const list = visibleGraves().sort((a, b) => b.ts - a.ts);
  el.classList.toggle("gone", !list.length);
  el.innerHTML = list.map((g) => `<button type="button" onclick="showOnMap({dim:'${esc(g.where.dim)}',x:${g.where.pos[0]},z:${g.where.pos[2]},zoom:4})">
    <img class="head" src="heads/${esc(g.uuid || "")}.png" width="16" height="16" alt=""> ${esc(g.name)}
    <span class="muted">${DIM_NAME[g.where.dim] || ""} · ${fmtAgo(g.ts)}</span></button>`).join("");
}

function setDeathMode(mode) {
  deathMode = deathMode === mode ? null : mode;
  document.querySelectorAll("#deathbtns button").forEach((b) => b.classList.toggle("on", b.dataset.mode === deathMode));
  if (deathMode && !graves.length) loadGraves();
  else drawGraves();
}
document.querySelectorAll("#deathbtns button").forEach((b) => b.addEventListener("click", () => setDeathMode(b.dataset.mode)));
setInterval(() => { if (deathMode) loadGraves(); }, 60000);

// ---------- export the map as an image ----------
// Stitches tiles on a canvas. At tile zoom z one pixel is 2^(3-z) blocks.

const LIMITS = matchMedia("(pointer: coarse)").matches
  ? { side: 4096, area: 16e6 }    // phones run out of canvas memory much sooner
  : { side: 8192, area: 50e6 };
let tileIndex = null;
let exportOpts = { area: "view", zoom: null, footer: true };
let exporting = false;

async function ensureTileIndex() {
  if (!tileIndex) {
    try { tileIndex = await getJSON("api/tiles"); } catch (e) { tileIndex = {}; }
  }
  return tileIndex;
}

function exportRect(area, z) {
  const world = WORLDS[mapDim];
  if (area === "all") {
    const list = tileIndex?.[world]?.[String(z)] || [];
    if (!list.length) return null;
    const xs = list.map((t) => t[0]), zs = list.map((t) => t[1]);
    return { x0: Math.min(...xs) * TILE, y0: Math.min(...zs) * TILE, x1: (Math.max(...xs) + 1) * TILE, y1: (Math.max(...zs) + 1) * TILE };
  }
  // In this CRS latitude grows downwards, so take min/max instead of assuming which corner is which.
  const b = map.getBounds();
  const a = map.project(b.getNorthWest(), z), c = map.project(b.getSouthEast(), z);
  return { x0: Math.floor(Math.min(a.x, c.x)), y0: Math.floor(Math.min(a.y, c.y)),
           x1: Math.ceil(Math.max(a.x, c.x)), y1: Math.ceil(Math.max(a.y, c.y)) };
}

function exportChoices(area) {
  const out = [];
  for (let z = NATIVE_ZOOM; z >= 0; z--) {
    const r = exportRect(area, z);
    if (!r) continue;
    const w = r.x1 - r.x0, h = r.y1 - r.y0;
    out.push({ z, w, h, ok: w <= LIMITS.side && h <= LIMITS.side && w * h <= LIMITS.area, blocks: 2 ** (NATIVE_ZOOM - z) });
  }
  return out;
}

async function openExport() {
  await ensureTileIndex();
  $("#exportpanel").classList.remove("gone");
  renderExport();
}
function closeExport() {
  if (!exporting) $("#exportpanel").classList.add("gone");
}

function fullmapLink() {
  const f = data?.fullmap?.[WORLDS[mapDim]];
  if (!f) return "";
  return `<div class="ep-full"><div class="ep-k">原清晰度完整地图（服务器每天凌晨生成）</div>
    <a class="dl" href="${esc(f.file)}?v=${f.ts}" download>下载 ${f.width} × ${f.height} · ${(f.bytes / 1048576).toFixed(1)} MB</a>
    <div class="muted">生成于 ${fmtDateTime(f.ts)} · 1 像素 = 1 格 · X ${f.x[0]} ~ ${f.x[1]} · Z ${f.z[0]} ~ ${f.z[1]}</div></div>`;
}

function renderExport(status = "") {
  const choices = exportChoices(exportOpts.area);
  if (!choices.some((c) => c.z === exportOpts.zoom && c.ok)) exportOpts.zoom = choices.find((c) => c.ok)?.z ?? null;
  const zoomRows = choices.map((c) => `<label class="opt ${c.ok ? "" : "off"}"><input type="radio" name="ez" value="${c.z}"
      ${c.z === exportOpts.zoom ? "checked" : ""} ${c.ok ? "" : "disabled"}>
      ${c.blocks === 1 ? "原始清晰度（1 像素 = 1 格）" : `1 像素 = ${c.blocks} 格`}
      <span class="muted">${c.w} × ${c.h}${c.ok ? "" : " · 太大"}</span></label>`).join("") || `<p class="muted">这个维度还没有地图。</p>`;
  const panel = $("#exportpanel");
  panel.innerHTML = `<div class="ep">
    <div class="ep-h">导出地图 · ${DIM_NAME[mapDim] || mapDim}<button type="button" class="x" aria-label="关闭">×</button></div>
    <div class="ep-k">范围</div>
    <label class="opt"><input type="radio" name="ea" value="view" ${exportOpts.area === "view" ? "checked" : ""}> 当前看到的区域</label>
    <label class="opt"><input type="radio" name="ea" value="all" ${exportOpts.area === "all" ? "checked" : ""}> 整个已探索区域</label>
    <div class="ep-k">清晰度</div>${zoomRows}
    <label class="opt"><input type="checkbox" name="ef" ${exportOpts.footer ? "checked" : ""}> 底部加上存档名、日期和比例</label>
    <button type="button" class="go" ${exportOpts.zoom === null || exporting ? "disabled" : ""}>${exporting ? "导出中…" : "导出 PNG"}</button>
    <div class="ep-s">${status}</div>${fullmapLink()}</div>`;
  panel.querySelector(".x").onclick = closeExport;
  panel.querySelectorAll("input[name=ea]").forEach((i) => (i.onchange = () => { exportOpts.area = i.value; renderExport(); }));
  panel.querySelectorAll("input[name=ez]").forEach((i) => (i.onchange = () => { exportOpts.zoom = +i.value; }));
  panel.querySelector("input[name=ef]").onchange = (e) => { exportOpts.footer = e.target.checked; };
  panel.querySelector(".go").onclick = runExport;
}

function loadImage(src) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);  // unexplored
    img.src = src;
  });
}

async function runExport() {
  if (exporting || exportOpts.zoom === null) return;
  const z = exportOpts.zoom, dim = mapDim, world = WORLDS[dim];
  const r = exportRect(exportOpts.area, z);
  if (!r) return;
  exporting = true;
  const w = r.x1 - r.x0, h = r.y1 - r.y0;
  const footer = exportOpts.footer ? Math.max(32, Math.round(w / 1600) * 32) : 0;
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h + footer;
  const g = canvas.getContext("2d");
  g.imageSmoothingEnabled = false;
  g.fillStyle = "#0b0b0e";
  g.fillRect(0, 0, canvas.width, canvas.height);

  const known = new Set((tileIndex?.[world]?.[String(z)] || []).map((t) => t.join(",")));
  const todo = [];
  for (let ty = Math.floor(r.y0 / TILE); ty * TILE < r.y1; ty++) {
    for (let tx = Math.floor(r.x0 / TILE); tx * TILE < r.x1; tx++) {
      if (!known.size || known.has(tx + "," + ty)) todo.push([tx, ty]);
    }
  }
  let done = 0;
  renderExport(`正在拼接 0 / ${todo.length} 块…`);
  for (let i = 0; i < todo.length; i += 6) {
    await Promise.all(todo.slice(i, i + 6).map(async ([tx, ty]) => {
      const img = await loadImage(`tiles/${world}/${z}/${tx}_${ty}.png`);
      if (img) g.drawImage(img, tx * TILE - r.x0, ty * TILE - r.y0);
      done++;
    }));
    renderExport(`正在拼接 ${done} / ${todo.length} 块…`);
  }

  const blocks = 2 ** (NATIVE_ZOOM - z);
  if (footer) {
    await document.fonts.load(`${footer / 2}px MCPixel`).catch(() => {});
    g.fillStyle = "#16161b";
    g.fillRect(0, h, w, footer);
    g.fillStyle = "#e6e6e6";
    g.font = `${footer / 2}px MCPixel, sans-serif`;
    g.textBaseline = "middle";
    const day = new Intl.DateTimeFormat("zh-CN", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
    g.fillText(`${data.title} · ${DIM_NAME[dim] || dim} · ${day} · 1 像素 = ${blocks} 格 · X ${r.x0 * blocks} ~ ${r.x1 * blocks} · Z ${r.y0 * blocks} ~ ${r.y1 * blocks}`,
      footer / 2, h + footer / 2);
  }
  renderExport("正在生成图片…");
  canvas.toBlob((blob) => {
    exporting = false;
    if (!blob) return renderExport("生成失败：图片太大，换一个低一点的清晰度试试。");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${data.world}-${world.replace("minecraft_", "")}-${new Date().toISOString().slice(0, 10)}.png`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 60000);
    renderExport(`已导出 ${w} × ${h + footer}，${(blob.size / 1048576).toFixed(1)} MB。`);
  }, "image/png");
}

$("#exportbtn").addEventListener("click", () => ($("#exportpanel").classList.contains("gone") ? openExport() : closeExport()));
