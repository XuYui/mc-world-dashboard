"use strict";

const DATA_URL = "dashboard/data.json";
const HEALTH_URL = "dashboard/health.json";
const LIVE_URL = "tiles/players.json";
const TZ = "Asia/Shanghai";
const COLORS = ["var(--c0)", "var(--c1)", "var(--c2)", "var(--c3)"];
const DIM_NAME = { "minecraft:overworld": "主世界", "minecraft:the_nether": "下界", "minecraft:the_end": "末地" };
const TAB_NAME = { story: "Minecraft", nether: "下界", end: "末地", adventure: "冒险", husbandry: "农牧业" };
const FRAME_NAME = { goal: "目标", challenge: "挑战" };
const ICON = {
  "minecraft:story/mine_stone": "item/wooden_pickaxe", "minecraft:story/smelt_iron": "item/iron_ingot",
  "minecraft:story/mine_diamond": "item/diamond", "minecraft:story/form_obsidian": "block/obsidian",
  "minecraft:story/enter_the_nether": "item/flint_and_steel", "minecraft:nether/find_fortress": "block/nether_bricks",
  "minecraft:nether/obtain_blaze_rod": "item/blaze_rod", "minecraft:story/follow_ender_eye": "item/ender_eye",
  "minecraft:story/enter_the_end": "block/end_stone", "minecraft:end/kill_dragon": "item/dragon_breath",
};

let data = null;
let live = null;        // squaremap players.json, or null if unreachable
let liveAt = 0;
let perHour = true;

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const now = () => Date.now() / 1000;

// ---------- formatting ----------

const fmtParts = (ts, opts) => new Intl.DateTimeFormat("zh-CN", { timeZone: TZ, ...opts }).format(new Date(ts * 1000));
const fmtDate = (ts) => fmtParts(ts, { month: "numeric", day: "numeric" }) + " " + fmtParts(ts, { weekday: "short" });
const fmtTime = (ts) => fmtParts(ts, { hour: "2-digit", minute: "2-digit", hour12: false });
const fmtDateTime = (ts) => fmtParts(ts, { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });

function fmtDur(secs) {
  secs = Math.max(0, Math.round(secs));
  const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60);
  if (h) return `${h} 小时 ${m} 分`;
  if (m) return `${m} 分钟`;
  return "不到 1 分钟";
}
function fmtAgo(ts) {
  const d = now() - ts;
  if (d < 90) return "刚刚";
  if (d < 3600) return `${Math.round(d / 60)} 分钟前`;
  if (d < 86400) return `${Math.round(d / 3600)} 小时前`;
  return `${Math.round(d / 86400)} 天前`;
}
const km = (cm) => (cm / 100000).toFixed(1) + " km";
const num = (n) => Number(n).toLocaleString("zh-CN");

// ---------- avatars (default skin face + hat layer) ----------

const headCache = {};
const headReady = {};
function headURL(skin) {
  if (!headCache[skin]) {
    headCache[skin] = new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        const c = document.createElement("canvas");
        c.width = c.height = 8;
        const g = c.getContext("2d");
        g.drawImage(img, 8, 8, 8, 8, 0, 0, 8, 8);
        g.drawImage(img, 40, 8, 8, 8, 0, 0, 8, 8);
        headReady[skin] = c.toDataURL();
        resolve(headReady[skin]);
      };
      img.onerror = () => resolve("");
      img.src = `dashboard/skins/${skin}.png`;
    });
  }
  return headCache[skin];
}
const head = (p, size) => headReady[p.skin]
  ? `<img class="head" width="${size}" height="${size}" alt="" src="${headReady[p.skin]}">`
  : `<img class="head" width="${size}" height="${size}" alt="" data-skin="${esc(p.skin)}">`;
function paintHeads(root = document) {
  root.querySelectorAll("img.head[data-skin]").forEach(async (img) => {
    const url = await headURL(img.dataset.skin);
    if (url) img.src = url;
    img.removeAttribute("data-skin");
  });
}

// ---------- map ----------

function mapURL({ dim = "minecraft:overworld", x, z, uuid, zoom } = {}) {
  const q = new URLSearchParams({ world: dim.replace(":", "_") });
  if (uuid) q.set("uuid", uuid.replace(/-/g, ""));
  if (x != null) q.set("x", x);
  if (z != null) q.set("z", z);
  if (zoom != null) q.set("zoom", zoom);
  return "map.html?" + q.toString();
}
function setDimButton(dim) {
  document.querySelectorAll("#dims button").forEach((b) => b.classList.toggle("on", b.dataset.dim === dim));
}
let mapDim = "minecraft:overworld";
function showOnMap(opts, keepFollow = false) {
  if (!keepFollow) stopFollow();
  mapDim = opts.dim || "minecraft:overworld";
  setDimButton(mapDim);
  $("#maploading").classList.remove("gone");
  mapWaitSince = Date.now();
  $("#map").src = mapURL(opts);
  openTab("map");
}
window.showOnMap = showOnMap;

// ---------- following a player on the map ----------
// squaremap drops its own follow on the first click; we drive the Leaflet map ourselves instead:
// zooming keeps the player centred, and after a drag the view drifts back to the player.

const MAP_SCALE = 3;      // squaremap's zoom.max, used to convert block coords to LatLng
const DRAG_GRACE = 3000;  // ms to leave the view alone after the viewer drags
let follow = null;        // { uuid, name }
let followMap = null, followPausedUntil = 0, followFirst = true;

function followPlayer(uuid, name, dim) {
  follow = { uuid: uuid.replace(/-/g, ""), name };
  followFirst = true;
  let ready = false;
  try { ready = !!$("#map").contentWindow.__sqMap?._loaded; } catch (e) {}
  if (ready && dim === mapDim) openTab("map");  // same map already open: just start following
  else showOnMap({ dim }, true);
  showFollowChip(`正在跟随 <b>${esc(name)}</b>`);
  followTick();
}
window.followPlayer = followPlayer;

function stopFollow() {
  follow = null;
  if (followMap) {
    followMap.options.scrollWheelZoom = followMap.options.touchZoom = followMap.options.doubleClickZoom = true;
  }
  $("#follow")?.classList.add("gone");
}

function showFollowChip(html) {
  const chip = $("#follow");
  chip.querySelector("span").innerHTML = html;
  chip.classList.remove("gone");
}

function attachFollowMap(map) {
  followMap = map;
  followFirst = true;
  map.on("dragstart", () => { followPausedUntil = Infinity; });
  map.on("dragend", () => { followPausedUntil = Date.now() + DRAG_GRACE; });
}

async function followTick() {
  if (!follow) return;
  let feed;
  try { feed = await getJSON(LIVE_URL); } catch (e) { return; }
  if (!follow) return;
  const p = feed.players.find((x) => x.uuid === follow.uuid);
  if (!p) {
    showFollowChip(`<b>${esc(follow.name)}</b> 已下线`);
    follow = null;
    return;
  }
  const dim = p.world.replace("_", ":");
  if (dim !== mapDim) {  // they went through a portal: switch the map, keep following
    showOnMap({ dim }, true);
    return;
  }
  let map = null;
  try { map = $("#map").contentWindow.__sqMap || null; } catch (e) {}
  if (!map || !map._loaded) return;
  if (map !== followMap) attachFollowMap(map);
  map.options.scrollWheelZoom = map.options.touchZoom = map.options.doubleClickZoom = "center";
  if (Date.now() < followPausedUntil) return;
  const target = map.unproject([p.x, p.z], MAP_SCALE);
  map.panTo(target, { animate: !followFirst, duration: 0.8 });
  followFirst = false;
}
setInterval(followTick, 1000);

// ---------- tabs ----------

function openTab(name) {
  document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.id === "tab-" + name));
  try { history.replaceState(null, "", name === "map" ? location.pathname : "#" + name); } catch (e) {}
}
document.querySelectorAll("nav button").forEach((b) => b.addEventListener("click", () => openTab(b.dataset.tab)));
window.addEventListener("hashchange", () => {
  const t = location.hash.slice(1);
  openTab(["progress", "sessions", "players"].includes(t) ? t : "map");
});

// ---------- status bar ----------

// Only touch the DOM when the markup changed, so a click is never lost to a re-render.
function setHTML(el, html) {
  if (el._html === html) return false;
  el._html = html;
  el.innerHTML = html;
  return true;
}

function liveFor(p) {
  if (!live) return null;
  const id = p.uuid.replace(/-/g, "");
  return live.players.find((x) => x.uuid === id || x.name === p.name) || null;
}

function gameClock() {
  const c = data.clock;
  if (!c || c.ticks == null) return null;
  let ticks = c.ticks;
  const anyOnline = live ? live.players.length > 0 : data.players.some((p) => p.online_since);
  if (anyOnline && c.saved) ticks += Math.min(now() - c.saved, 600) * 20;  // server pauses when empty
  const day = Math.floor(ticks / 24000) + 1;
  const t = ticks % 24000;
  const mins = Math.floor(((t / 1000 + 6) % 24) * 60);
  const night = t >= 13000 && t < 23000;
  return { day, night, hhmm: `${String(Math.floor(mins / 60)).padStart(2, "0")}:${String(mins % 60).padStart(2, "0")}` };
}

function renderStatus() {
  const s = data.server;
  const reachable = live !== null || s.running;
  const chips = [];
  chips.push(reachable
    ? `<span class="chip ok"><b>● 运行中</b>${s.since ? " · 已运行 " + fmtDur(now() - s.since) : ""}</span>`
    : `<span class="chip bad"><b>● 离线</b></span>`);
  const clk = gameClock();
  if (clk) {
    const w = data.clock.weather === "thunder" ? "雷雨" : data.clock.weather === "rain" ? "下雨" : "晴";
    chips.push(`<span class="chip">${clk.night ? "🌙" : "☀️"} <b>第 ${clk.day} 天</b> ${clk.hhmm} · ${w}</span>`);
  }
  chips.push(healthChip());
  chips.push(`<span class="chip">每天 ${s.restart} 自动重启</span>`);
  setHTML($("#server"), chips.join(""));

  const rows = data.players.map((p) => {
    const l = liveFor(p);
    const on = l || (live === null && p.online_since);
    if (on) {
      const dim = l ? l.world.replace("_", ":") : p.nbt?.dim;
      const hp = l ? l.health : p.nbt?.health;
      const food = p.nbt?.food;
      const since = p.online_since ? "在线 " + fmtDur(now() - p.online_since) : "刚刚上线";
      return `<div class="person on" title="在地图上查看" onclick="followPlayer('${p.uuid}','${esc(p.name)}','${dim}')">
        ${head(p, 30)}
        <div class="who"><span class="name">${esc(p.name)}</span>
          <span class="sub"><i class="dim" style="background:var(--${dim.split(":")[1]})"></i>${DIM_NAME[dim] || dim} · ${since}</span>
          <span class="vitals" title="生命 ${hp ?? "?"}/20 · 饱食度 ${food ?? "?"}/20（饱食度随存档约 5 分钟更新）">
            <span class="meter hp"><i style="width:${((hp ?? 0) / 20) * 100}%"></i></span>${hp ?? "?"}
            <span class="meter food"><i style="width:${((food ?? 0) / 20) * 100}%"></i></span>${food ?? "?"}
          </span></div></div>`;
    }
    return `<div class="person off">${head(p, 30)}<div class="who"><span class="name">${esc(p.name)}</span>
      <span class="sub">${p.last_seen ? fmtAgo(p.last_seen) + "在线" : "离线"}</span></div></div>`;
  });
  if (setHTML($("#online"), rows.join(""))) paintHeads($("#online"));
}

// ---------- re-rendering without losing what the viewer opened ----------

// Data refreshes every minute; keep expanded <details> (keyed by data-k) and the scroll position.
function paint(el, html) {
  if (el._html === html) return false;
  const open = new Set([...el.querySelectorAll("details[open][data-k]")].map((d) => d.dataset.k));
  const top = el.scrollTop;
  el._html = html;
  el.innerHTML = html;
  el.querySelectorAll("details[data-k]").forEach((d) => { if (open.has(d.dataset.k)) d.open = true; });
  el.scrollTop = top;
  return true;
}

// Close a long <details> from a button at its bottom and bring its header back into view.
function foldDetails(btn) {
  const d = btn.closest("details");
  d.open = false;
  d.querySelector("summary").scrollIntoView({ block: "nearest" });
}
window.foldDetails = foldDetails;

// ---------- mainline ----------

function renderProgress() {
  const pr = data.progress;
  const nodes = pr.mainline.map((n) => `<div class="node ${n.ts ? "done" : ""}">
      <span class="frame-ico">${ICON[n.id] ? `<img class="ico" src="dashboard/tex/${ICON[n.id]}.png" alt="">` : ""}</span>
      <div class="t">${esc(n.title)}</div><div class="d">${esc(n.desc)}</div>
      <div class="when">${n.ts ? "✓ " + fmtDateTime(n.ts) : "未完成"}</div></div>`).join("");
  const pct = (pr.done / pr.total) * 100;
  const groups = {};
  pr.all.forEach((a) => (groups[a.tab] = groups[a.tab] || []).push(a));
  const all = Object.entries(groups).map(([tab, list]) => {
    const done = list.filter((a) => a.ts).length;
    return `<h3>${TAB_NAME[tab] || tab} · ${done}/${list.length}</h3>` + list.map((a) => `
      <div class="adv ${a.ts ? "done" : ""}" style="padding-left:${a.depth * 12}px">
        <div><span class="name">${esc(a.title)}</span>${FRAME_NAME[a.frame] ? `<span class="frame ${a.frame}">${FRAME_NAME[a.frame]}</span>` : ""}
        <div class="desc">${esc(a.desc)}</div></div>
        <div class="ts">${a.ts ? fmtDateTime(a.ts) : "—"}</div></div>`).join("");
  }).join("");
  paint($("#tab-progress"), `<div class="wrap">
    <h2>主线进度</h2>
    <div class="route">${nodes}</div>
    <div class="card total"><b>全队成就 ${pr.done} / ${pr.total}</b> <span class="muted">（${pct.toFixed(0)}%）</span>
      <div class="progress"><i style="width:${pct}%"></i></div></div>
    <details class="all" data-k="all"><summary>全部成就</summary>${all}</details></div>`);
}

// ---------- sessions ----------

function renderSessions() {
  const byName = Object.fromEntries(data.players.map((p) => [p.name, p]));
  const cards = data.sessions.map((s) => {
    const end = s.end ?? now();
    const dur = end - s.start;
    const kind = s.ongoing ? `<span class="tag live">进行中</span>` : s.multi ? `<span class="tag">联机</span>` : `<span class="tag">独自游玩</span>`;
    const ppl = s.players.map((p) => `<span class="pp">${head(byName[p.name] || {}, 18)}${esc(p.name)} <span class="muted">${fmtDur(p.secs)}</span></span>`).join("");
    const adv = s.advancements.length ? `<ul class="list">${s.advancements.map((a) => `<li><span class="tm">${fmtTime(a.ts)}</span>${esc(a.name)} 获得成就「${esc(a.title)}」${a.team_first ? ' <span class="first">★ 全队首次</span>' : ""}</li>`).join("")}</ul>` : "";
    let deaths = "";
    if (s.deaths.length) {
      const cnt = {};
      s.deaths.forEach((d) => (cnt[d.name] = (cnt[d.name] || 0) + 1));
      const sum = Object.entries(cnt).sort((a, b) => b[1] - a[1]).map(([n, c]) => `${esc(n)} ×${c}`).join("，");
      const items = s.deaths.map((d) => `<li><span class="tm">${fmtTime(d.ts)}</span>${esc(d.text)}${d.where ? `<button class="linkbtn" onclick="showOnMap({dim:'${d.where.dim}',x:${d.where.pos[0]},z:${d.where.pos[2]},zoom:3})">在地图上看</button>` : ""}</li>`).join("");
      deaths = `<details data-k="d${s.no}"><summary>💀 死亡 ${s.deaths.length} 次：${sum}</summary><ul class="list">${items}</ul></details>`;
    }
    let stats = "";
    if (s.stats) {
      stats = `<div class="mini">${Object.entries(s.stats).map(([n, v]) => `${esc(n)}：杀怪 ${v.mob_kills} · 挖掘 ${v.mined} · 放置 ${v.placed} · 移动 ${v.km} km${v.diamond_ore ? ` · 钻石矿 ${v.diamond_ore}` : ""}`).join("<br>")}</div>`;
    }
    return `<div class="card sess">
      <div class="sess-h"><div><span class="no">第 ${s.no} 次</span>${kind}</div>
        <div class="muted">${fmtDate(s.start)} ${fmtTime(s.start)}–${s.ongoing ? "现在" : fmtTime(end)} · ${fmtDur(dur)}</div></div>
      <div class="headline">${esc(s.headline)}</div>
      <div class="row">${ppl}</div>${adv}${deaths}${stats}</div>`;
  }).join("");
  paint($("#tab-sessions"), `<div class="wrap"><h2>联机日志</h2>${cards || '<div class="empty">还没有记录</div>'}</div>`);
  paintHeads($("#tab-sessions"));
}

// ---------- radar ----------

const AXES = [
  { name: "战斗", subs: ["mob_kills", "damage_dealt"] },
  { name: "挖矿", subs: ["mined_total", "ore_points"] },
  { name: "建造", subs: ["placed"] },
  { name: "探索", subs: ["land_cm", "water_cm"] },
  { name: "生存", survival: true },
  { name: "农业厨艺", subs: ["bred", "fish", "harvest", "eaten"] },
];

function radarScores() {
  const ps = data.players;
  const val = (p, k) => (perHour ? p.stats[k] / Math.max(p.hours, 0.1) : p.stats[k]);
  const out = ps.map(() => []);
  AXES.forEach((ax, i) => {
    if (ax.survival) {
      const v = ps.map((p) => p.hours / (p.stats.deaths + 1));
      const mx = Math.max(...v) || 1;
      v.forEach((x, j) => (out[j][i] = (x / mx) * 100));
      return;
    }
    const parts = ax.subs.map((k) => {
      const v = ps.map((p) => val(p, k));
      const mx = Math.max(...v) || 1;
      return v.map((x) => x / mx);
    });
    ps.forEach((_, j) => (out[j][i] = (parts.reduce((a, s) => a + s[j], 0) / parts.length) * 100));
  });
  return out;
}

function radarSVG(series) {
  const R = 100, cx = 160, cy = 130, n = AXES.length;
  const pt = (i, r) => {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / n;
    return [cx + Math.cos(a) * r, cy + Math.sin(a) * r];
  };
  let g = "";
  [0.25, 0.5, 0.75, 1].forEach((f) => {
    g += `<polygon points="${AXES.map((_, i) => pt(i, R * f).join(",")).join(" ")}" fill="none" stroke="var(--line)"/>`;
  });
  AXES.forEach((ax, i) => {
    const [x, y] = pt(i, R);
    const [tx, ty] = pt(i, R + 16);
    g += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="var(--line)"/>`;
    g += `<text x="${tx}" y="${ty + 4}" text-anchor="middle">${ax.name}</text>`;
  });
  series.forEach(({ scores, color }) => {
    const pts = scores.map((s, i) => pt(i, (Math.max(s, 2) / 100) * R).join(",")).join(" ");
    g += `<polygon points="${pts}" fill="${color}" fill-opacity="${series.length > 1 ? 0.12 : 0.3}" stroke="${color}" stroke-width="2"/>`;
  });
  return `<svg class="radar" viewBox="0 0 320 260" role="img">${g}</svg>`;
}

function renderPlayers() {
  const scores = radarScores();
  const ps = data.players;
  const all = radarSVG(ps.map((p, i) => ({ scores: scores[i], color: COLORS[i % 4] })));
  const legend = ps.map((p, i) => `<span style="--c:${COLORS[i % 4]}">${esc(p.name)}</span>`).join("");
  const cards = ps.map((p, i) => {
    const s = p.stats;
    const top = p.causes[0];
    const ld = p.nbt?.last_death;
    const kv = [
      ["游戏时长", p.hours.toFixed(1) + " 小时"],
      ["等级", p.nbt ? p.nbt.level + " 级" : "—"],
      ["死亡", s.deaths + " 次"],
      ["最常死于", top ? `${esc(top[0])} ×${top[1]}` : "—"],
      ["杀怪", num(s.mob_kills)],
      ["挖钻石矿", s.diamond_ore],
      ["挖掘方块", num(s.mined_total)],
      ["放置方块", num(s.placed)],
      ["陆地移动", km(s.land_cm)],
      ["水上移动", km(s.water_cm)],
      ["繁殖 / 钓鱼", `${s.bred} / ${s.fish}`],
      ["成就", p.advancements + " 个"],
    ].map(([k, v]) => `<div><span>${k}</span><span>${v}</span></div>`).join("");
    const row = (b) => `<li><span class="badge">${esc(b.title)}</span><span class="why">${esc(b.why)}</span></li>`;
    const shown = p.badges.slice(0, 4), more = p.badges.slice(4);
    const badges = p.badges.length ? `<ul class="titles">${shown.map(row).join("")}</ul>` + (more.length
      ? `<details class="more-titles" data-k="t-${esc(p.name)}"><summary><span class="when-closed">更多称号（${more.length}）</span><span class="when-open">收起称号</span></summary><ul class="titles">${more.map(row).join("")}</ul><button type="button" class="fold" onclick="foldDetails(this)">收起称号</button></details>`
      : "") : "";
    const death = ld ? `<div class="mini">上次死亡：${DIM_NAME[ld.dim] || ld.dim} (${ld.pos.join(", ")})
      <button class="linkbtn" onclick="showOnMap({dim:'${ld.dim}',x:${ld.pos[0]},z:${ld.pos[2]},zoom:3})">在地图上看</button></div>` : "";
    return `<div class="card pcard">
      <div class="top">${head(p, 48)}<div><div class="nm">${esc(p.name)}</div>
        <div class="ttl">${esc(p.title || "")}</div></div></div>
      ${badges ? `<div class="badges">${badges}</div>` : ""}
      ${radarSVG([{ scores: scores[i], color: COLORS[i % 4] }])}
      <div class="kv">${kv}</div>${death}</div>`;
  }).join("");
  paint($("#tab-players"), `<div class="wrap">
    <div class="sess-h"><h2>玩家</h2>
      <div class="toggle"><button data-m="1" class="${perHour ? "on" : ""}">每小时</button><button data-m="0" class="${perHour ? "" : "on"}">总量</button></div></div>
    <p class="muted" style="margin-top:0">${perHour ? "按每小时游戏时间算，看的是玩法风格。" : "按累计总量算，看的是总贡献。"}每根轴以四人中的最高者为满分；「生存」是平均每次死亡之间活了多久。</p>
    <div class="card">${all}<div class="legend">${legend}</div></div>
    <div class="cards">${cards}</div></div>`);
  $("#tab-players").querySelectorAll(".toggle button").forEach((b) => b.addEventListener("click", () => {
    perHour = b.dataset.m === "1";
    renderPlayers();
  }));
  paintHeads($("#tab-players"));
}

// ---------- loading ----------

async function getJSON(url) {
  const r = await fetch(url + (url.includes("?") ? "&" : "?") + "t=" + Date.now(), { cache: "no-store" });
  if (!r.ok) throw new Error(r.status);
  return r.json();
}

async function loadData() {
  try {
    const d = await getJSON(DATA_URL);
    const first = !data;
    const changed = !data || d.generated !== data.generated;
    data = d;
    if (d.title) {
      document.title = d.title;
      $("#site-title").textContent = d.title;
    }
    if (changed) {
      renderProgress();
      renderSessions();
      renderPlayers();
    }
    renderStatus();
    if (first) {
      const t = location.hash.slice(1);
      if (["progress", "sessions", "players"].includes(t)) openTab(t);
    }
  } catch (e) {
    if (!data) $("#tab-progress").innerHTML = '<div class="empty">数据加载失败</div>';
  }
}

async function loadLive() {
  try {
    live = await getJSON(LIVE_URL);
    liveAt = now();
  } catch (e) {
    if (now() - liveAt > 15) live = null;
  }
  if (data) renderStatus();
}

$("#follow button").addEventListener("click", stopFollow);
document.querySelectorAll("#dims button").forEach((b) => b.addEventListener("click", () => {
  if (!b.classList.contains("on")) showOnMap({ dim: b.dataset.dim });
}));

// ---------- server health (DashboardHealth plugin) ----------

let health = null;
let healthOpen = false;

async function loadHealth() {
  try { health = await getJSON(HEALTH_URL); } catch (e) { health = null; }
  if (data) renderStatus();
  if (healthOpen) renderHealth();
}

function anyoneOnline() {
  return live ? live.players.length > 0 : !!data?.players.some((p) => p.online_since);
}

// "ok" | "warn" | "bad" | "idle" | null (no plugin)
function healthState() {
  if (!health) return null;
  if (now() - health.ts / 1000 > 30) return anyoneOnline() ? "stale" : "idle";
  const tps = health.tps[0];
  if (tps >= 18 && health.mspt < 45) return "ok";
  if (tps >= 15) return "warn";
  return "bad";
}

function healthChip() {
  const st = healthState();
  if (!st) return "";
  const text = st === "idle" ? "<b>空闲</b> · 无人时服务器暂停"
    : st === "stale" ? "<b>状态未更新</b>"
    : `<b>TPS ${health.tps[0].toFixed(1)}</b> · ${Math.round(health.mspt)} ms`;
  return `<span class="chip health ${st}" role="button" tabindex="0" onclick="toggleHealth()" title="服务器负载，点击查看详情">${text}</span>`;
}

function toggleHealth() {
  healthOpen = !healthOpen;
  $("#healthpanel").classList.toggle("gone", !healthOpen);
  if (healthOpen) renderHealth();
}
window.toggleHealth = toggleHealth;

const gb = (b) => (b / 1073741824).toFixed(2) + " GB";

function sparkline(values, lo, hi, color) {
  if (values.length < 2) return `<div class="spark empty">数据积累中</div>`;
  const w = 240, h = 40;
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * w;
    const y = h - ((Math.min(Math.max(v, lo), hi) - lo) / (hi - lo || 1)) * (h - 4) - 2;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>`;
}

function renderHealth() {
  const el = $("#healthpanel");
  if (!health) {
    setHTML(el, `<div class="wrap muted">没有服务器负载数据（需要 DashboardHealth 插件）。</div>`);
    return;
  }
  const st = healthState();
  const hist = health.history || [];
  const mem = health.mem_used / health.mem_max;
  const note = st === "idle" ? `<p class="muted">没人在线时服务器会暂停运算，下面是 ${fmtAgo(health.ts / 1000)}的数据。</p>`
    : st === "stale" ? `<p class="muted">负载数据 ${fmtAgo(health.ts / 1000)}更新，插件可能没在运行。</p>` : "";
  setHTML(el, `<div class="wrap">${note}
    <div class="hgrid">
      <div class="hcell"><div class="hk">TPS（1 / 5 / 15 分钟）</div><div class="hv">${health.tps.map((t) => t.toFixed(1)).join(" / ")}</div>
        ${sparkline(hist.map((x) => x.tps), 10, 20, "#8dff6a")}<div class="hn">满分 20，低于 18 会感觉卡</div></div>
      <div class="hcell"><div class="hk">每刻耗时</div><div class="hv">${health.mspt.toFixed(1)} ms</div>
        ${sparkline(hist.map((x) => x.mspt), 0, 60, "#ffcc4d")}<div class="hn">超过 50 ms 就跟不上 20 TPS</div></div>
      <div class="hcell"><div class="hk">内存（Java 堆）</div><div class="hv">${gb(health.mem_used)} / ${gb(health.mem_max)}</div>
        <div class="hbar"><i style="width:${(mem * 100).toFixed(0)}%"></i></div>
        ${sparkline(hist.map((x) => x.mem), 0, health.mem_max, "#62c3ff")}</div>
      <div class="hcell"><div class="hk">CPU</div><div class="hv">服务器 ${health.cpu_process.toFixed(0)}% · 整机 ${health.cpu_system.toFixed(0)}%</div>
        <div class="hn">${health.cores} 核，100% 表示全部核心占满</div>
        <div class="hk" style="margin-top:8px">已加载</div><div class="hv">${num(health.chunks)} 区块 · ${num(health.entities)} 实体</div></div>
    </div>
    <p class="muted hfoot">图表为最近一小时，每分钟一个点。数据更新于 ${fmtAgo(health.ts / 1000)}。</p></div>`);
}

// ---------- export the map as an image ----------
// Stitches squaremap's tiles (tiles/<world>/<zoom>/<x>_<z>.png, 512 px each) on a canvas.
// At tile zoom z one pixel is 2^(3-z) blocks; zoom 3 is 1:1.

const TILE = 512, MAX_ZOOM = 3;
const LIMITS = matchMedia("(pointer: coarse)").matches
  ? { side: 4096, area: 16e6 }    // phones run out of canvas memory much sooner
  : { side: 8192, area: 50e6 };
const DIM_LABEL = { "minecraft:overworld": "主世界", "minecraft:the_nether": "下界", "minecraft:the_end": "末地" };
let exportOpts = { area: "view", zoom: null, footer: true };
let exporting = false;

// Pixel rectangle (at tile zoom z) to export, or null.
function exportRect(area, z) {
  const world = mapDim.replace(":", "_");
  if (area === "all") {
    const tiles = data?.tiles?.[world]?.[String(z)] || [];
    if (!tiles.length) return null;
    const xs = tiles.map((t) => t[0]), zs = tiles.map((t) => t[1]);
    return { x0: Math.min(...xs) * TILE, y0: Math.min(...zs) * TILE,
             x1: (Math.max(...xs) + 1) * TILE, y1: (Math.max(...zs) + 1) * TILE };
  }
  let map = null;
  try { map = $("#map").contentWindow.__sqMap; } catch (e) {}
  if (!map) return null;
  const b = map.getBounds();
  const a = map.project(b.getNorthWest(), z), c = map.project(b.getSouthEast(), z);
  return { x0: Math.floor(a.x), y0: Math.floor(a.y), x1: Math.ceil(c.x), y1: Math.ceil(c.y) };
}

function exportChoices(area) {
  const out = [];
  for (let z = MAX_ZOOM; z >= 0; z--) {
    const r = exportRect(area, z);
    if (!r) continue;
    const w = r.x1 - r.x0, h = r.y1 - r.y0;
    const ok = w <= LIMITS.side && h <= LIMITS.side && w * h <= LIMITS.area;
    out.push({ z, w, h, ok, blocks: 2 ** (MAX_ZOOM - z) });
  }
  return out;
}

function openExport() {
  $("#exportpanel").classList.remove("gone");
  renderExport();
}
function closeExport() {
  if (!exporting) $("#exportpanel").classList.add("gone");
}
window.openExport = openExport;
window.closeExport = closeExport;

function renderExport(status = "") {
  const choices = exportChoices(exportOpts.area);
  if (!choices.some((c) => c.z === exportOpts.zoom && c.ok)) exportOpts.zoom = choices.find((c) => c.ok)?.z ?? null;
  const zoomRows = choices.map((c) => `<label class="opt ${c.ok ? "" : "off"}"><input type="radio" name="ez" value="${c.z}"
      ${c.z === exportOpts.zoom ? "checked" : ""} ${c.ok ? "" : "disabled"}>
      ${c.blocks === 1 ? "原始清晰度（1 像素 = 1 格）" : `1 像素 = ${c.blocks} 格`}
      <span class="muted">${c.w} × ${c.h}${c.ok ? "" : " · 太大"}</span></label>`).join("") || `<p class="muted">这个维度还没有地图。</p>`;
  $("#exportpanel").innerHTML = `<div class="ep">
    <div class="ep-h">导出地图 · ${DIM_LABEL[mapDim] || mapDim}<button type="button" class="x" onclick="closeExport()" aria-label="关闭">×</button></div>
    <div class="ep-k">范围</div>
    <label class="opt"><input type="radio" name="ea" value="view" ${exportOpts.area === "view" ? "checked" : ""}> 当前看到的区域</label>
    <label class="opt"><input type="radio" name="ea" value="all" ${exportOpts.area === "all" ? "checked" : ""}> 整个已探索区域</label>
    <div class="ep-k">清晰度</div>${zoomRows}
    <label class="opt"><input type="checkbox" name="ef" ${exportOpts.footer ? "checked" : ""}> 底部加上存档名、日期和比例</label>
    <button type="button" class="go" ${exportOpts.zoom === null || exporting ? "disabled" : ""}>${exporting ? "导出中…" : "导出 PNG"}</button>
    <div class="ep-s">${status}</div>${fullmapLink()}</div>`;
  const panel = $("#exportpanel");
  panel.querySelectorAll("input[name=ea]").forEach((i) => i.addEventListener("change", () => { exportOpts.area = i.value; renderExport(); }));
  panel.querySelectorAll("input[name=ez]").forEach((i) => i.addEventListener("change", () => { exportOpts.zoom = +i.value; }));
  panel.querySelector("input[name=ef]").addEventListener("change", (e) => { exportOpts.footer = e.target.checked; });
  panel.querySelector(".go").addEventListener("click", runExport);
}

// Full-resolution image of the whole dimension, stitched on the server every night (fullmap.py).
function fullmapLink() {
  const f = data?.fullmap?.[mapDim.replace(":", "_")];
  if (!f) return "";
  return `<div class="ep-full"><div class="ep-k">原清晰度完整地图（服务器每天凌晨生成）</div>
    <a class="dl" href="${f.file}?v=${f.ts}" download>下载 ${f.width} × ${f.height} · ${(f.bytes / 1048576).toFixed(1)} MB</a>
    <div class="muted">生成于 ${fmtDateTime(f.ts)} · 1 像素 = 1 格 · X ${f.x[0]} ~ ${f.x[1]} · Z ${f.z[0]} ~ ${f.z[1]}</div></div>`;
}

function loadImage(src) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);  // unexplored tile
    img.src = src;
  });
}

async function runExport() {
  if (exporting || exportOpts.zoom === null) return;
  const z = exportOpts.zoom, area = exportOpts.area, dim = mapDim;
  const r = exportRect(area, z);
  if (!r) return;
  exporting = true;
  const world = dim.replace(":", "_");
  const w = r.x1 - r.x0, h = r.y1 - r.y0;
  const footer = exportOpts.footer ? Math.max(32, Math.round(w / 1600) * 32) : 0;
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h + footer;
  const g = canvas.getContext("2d");
  g.imageSmoothingEnabled = false;
  g.fillStyle = "#0b0b0e";
  g.fillRect(0, 0, canvas.width, canvas.height);

  const tiles = [];
  for (let ty = Math.floor(r.y0 / TILE); ty * TILE < r.y1; ty++) {
    for (let tx = Math.floor(r.x0 / TILE); tx * TILE < r.x1; tx++) tiles.push([tx, ty]);
  }
  const known = new Set((data?.tiles?.[world]?.[String(z)] || []).map((t) => t.join(",")));
  const todo = tiles.filter((t) => known.size === 0 || known.has(t.join(",")));
  let done = 0;
  const stamp = Date.now();
  renderExport(`正在拼接 0 / ${todo.length} 块…`);
  for (let i = 0; i < todo.length; i += 6) {  // a few at a time
    await Promise.all(todo.slice(i, i + 6).map(async ([tx, ty]) => {
      const img = await loadImage(`tiles/${world}/${z}/${tx}_${ty}.png?t=${stamp}`);
      if (img) g.drawImage(img, tx * TILE - r.x0, ty * TILE - r.y0);
      done++;
    }));
    renderExport(`正在拼接 ${done} / ${todo.length} 块…`);
  }

  const blocks = 2 ** (MAX_ZOOM - z);
  const bx0 = Math.round(r.x0 * blocks), bz0 = Math.round(r.y0 * blocks);
  const bx1 = Math.round(r.x1 * blocks), bz1 = Math.round(r.y1 * blocks);
  if (footer) {
    await document.fonts.load(`${footer / 2}px MCPixel`).catch(() => {});
    g.fillStyle = "#16161b";
    g.fillRect(0, h, w, footer);
    g.fillStyle = "#e6e6e6";
    g.font = `${footer / 2}px MCPixel, sans-serif`;
    g.textBaseline = "middle";
    const day = new Intl.DateTimeFormat("zh-CN", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
    g.fillText(`${data.title || data.world} · ${DIM_LABEL[dim] || dim} · ${day} · 1 像素 = ${blocks} 格 · X ${bx0} ~ ${bx1} · Z ${bz0} ~ ${bz1}`,
      footer / 2, h + footer / 2);
  }

  renderExport("正在生成图片…");
  canvas.toBlob((blob) => {
    exporting = false;
    if (!blob) {
      renderExport("生成失败：图片太大，换一个低一点的清晰度试试。");
      return;
    }
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

// ---------- death layers (DeathMarkers plugin) ----------
// Two mutually exclusive buttons drive squaremap's own layer checkboxes inside the map frame:
// "recent" = each player's latest death, "all" = every recorded death, none = no gravestones.
// The two entries are hidden in squaremap's layer list so the buttons stay the only switch.

const DEATH_LAYERS = { all: "deathmarkers", recent: "deathmarkers_recent" };
let deathMode = null;
const layerNames = {};  // world -> { layer id: label shown in squaremap's layer list }

async function deathLayerNames(world) {
  if (!layerNames[world]) {
    layerNames[world] = getJSON(`tiles/${world}/markers.json`)
      .then((layers) => Object.fromEntries(layers.map((l) => [l.id, l.name])))
      .catch(() => { delete layerNames[world]; return {}; });
  }
  return layerNames[world];
}

async function syncDeathLayers() {
  let doc;
  try { doc = $("#map").contentDocument; } catch (e) { return; }
  const labels = doc ? [...doc.querySelectorAll(".leaflet-control-layers-overlays label")] : [];
  if (!labels.length) return;
  const names = await deathLayerNames(mapDim.replace(":", "_"));
  for (const [mode, id] of Object.entries(DEATH_LAYERS)) {
    const label = labels.find((l) => l.textContent.trim() === names[id]);
    if (!label) continue;
    label.style.display = "none";
    const box = label.querySelector("input");
    if (box && box.checked !== (deathMode === mode)) box.click();
  }
}

function setDeathMode(mode) {
  deathMode = deathMode === mode ? null : mode;
  document.querySelectorAll("#deathbtns button").forEach((b) => b.classList.toggle("on", b.dataset.mode === deathMode));
  syncDeathLayers();
}
document.querySelectorAll("#deathbtns button").forEach((b) => b.addEventListener("click", () => setDeathMode(b.dataset.mode)));
setInterval(syncDeathLayers, 1000);  // re-apply after the map reloads (dimension switch, follow)

// Hide the loading hint as soon as squaremap has drawn its first tile (or after 15 s regardless).
let mapWaitSince = Date.now();
setInterval(() => {
  const hint = $("#maploading");
  if (hint.classList.contains("gone")) return;
  let ready = false;
  try { ready = !!$("#map").contentDocument?.querySelector(".leaflet-tile-loaded"); } catch (e) { ready = true; }
  if (ready || Date.now() - mapWaitSince > 15000) hint.classList.add("gone");
}, 250);

loadData().then(loadLive).then(loadHealth);
setInterval(loadHealth, 5000);
setInterval(loadData, 30000);
setInterval(loadLive, 3000);
