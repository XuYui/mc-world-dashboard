"use strict";
// Page shell: status bar, notices, and the 主线 / 联机日志 / 玩家 tabs. The map lives in map.js.
// All URLs are relative, so the page also works behind a path prefix.

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
const SESSION_PAGE = 20;

let data = null;          // /api/summary
let liveResp = null;      // /api/live
let liveOkAt = Date.now();
let sessions = [];        // loaded pages of /api/sessions, newest first
let sessionsTotal = 0;
let perHour = true;
let healthOpen = false;

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
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
const gb = (b) => (b / 1073741824).toFixed(2) + " GB";
const hp = (h) => Number((+h || 0).toFixed(1));  // health arrives as e.g. 17.23

// Player head: the default skin the game gives this UUID (made by the backend).
const head = (p, size) => `<img class="head" width="${size}" height="${size}" alt="" src="heads/${esc(p?.uuid || "00000000000000000000000000000000")}.png">`;

// ---------- DOM helpers ----------

// Only touch the DOM when the markup changed, so a click is never lost to a re-render.
function setHTML(el, html) {
  if (el._html === html) return false;
  el._html = html;
  el.innerHTML = html;
  return true;
}

// Like setHTML, but keeps expanded <details data-k> and the scroll position.
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

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-cache" });  // revalidates: unchanged answers are a 304
  if (!r.ok) throw new Error(r.status);
  return r.json();
}

// ---------- tabs ----------

function openTab(name) {
  document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("on", t.id === "tab-" + name));
  try { history.replaceState(null, "", name === "map" ? location.pathname : "#" + name); } catch (e) {}
  if (name === "map" && window.mapResized) window.mapResized();
}
document.querySelectorAll("nav button").forEach((b) => b.addEventListener("click", () => openTab(b.dataset.tab)));
window.addEventListener("hashchange", () => {
  const t = location.hash.slice(1);
  openTab(["progress", "sessions", "players"].includes(t) ? t : "map");
});

// ---------- live state (WorldDashboard plugin, via /api/live) ----------

function livePlayers() {
  const l = liveResp?.live;
  return l && !liveResp.paused ? l.players || [] : [];
}
function liveFor(p) {
  return livePlayers().find((x) => x.uuid === p.uuid || x.name === p.name) || null;
}
function serverHealth() {
  return liveResp?.live?.health || null;
}

function gameClock() {
  const c = data.clock;
  if (!c || c.ticks == null) return null;
  let ticks = c.ticks;
  if (livePlayers().length && c.saved) ticks += Math.min(now() - c.saved, 600) * 20;  // server pauses when empty
  const day = Math.floor(ticks / 24000) + 1;
  const t = ticks % 24000;
  const mins = Math.floor(((t / 1000 + 6) % 24) * 60);
  return { day, night: t >= 13000 && t < 23000,
           hhmm: `${String(Math.floor(mins / 60)).padStart(2, "0")}:${String(mins % 60).padStart(2, "0")}` };
}

// "ok" | "warn" | "bad" | "idle" | null (no plugin data)
function healthState() {
  const h = serverHealth();
  if (!h) return null;
  if (liveResp.paused) return "idle";
  const tps = h.tps[0];
  if (tps >= 18 && h.mspt < 45) return "ok";
  return tps >= 15 ? "warn" : "bad";
}

function healthChip() {
  const st = healthState();
  if (!st) return "";
  const h = serverHealth();
  const text = st === "idle" ? "<b>空闲</b> · 无人时服务器暂停" : `<b>TPS ${h.tps[0].toFixed(1)}</b> · ${Math.round(h.mspt)} ms`;
  return `<span class="chip health ${st}" role="button" tabindex="0" onclick="toggleHealth()" title="服务器负载，点击查看详情">${text}</span>`;
}

function renderStatus() {
  if (!data) return;
  const s = data.server;
  const l = liveResp?.live;
  const running = l ? !l.stopped && (!liveResp.paused || s.running) : s.running;
  const chips = [running
    ? `<span class="chip ok"><b>● 运行中</b>${s.since ? " · 已运行 " + fmtDur(now() - s.since) : ""}</span>`
    : `<span class="chip bad"><b>● 离线</b></span>`];
  const clk = gameClock();
  if (clk) {
    const w = data.clock.weather === "thunder" ? "雷雨" : data.clock.weather === "rain" ? "下雨" : "晴";
    chips.push(`<span class="chip">${clk.night ? "🌙" : "☀️"} <b>第 ${clk.day} 天</b> ${clk.hhmm} · ${w}</span>`);
  }
  chips.push(healthChip());
  chips.push(`<span class="chip">每天 ${esc(s.restart)} 自动重启</span>`);
  setHTML($("#server"), chips.join(""));

  const rows = data.players.map((p) => {
    const lp = liveFor(p);
    if (lp) {
      const since = p.online_since ? "在线 " + fmtDur(now() - p.online_since) : "刚刚上线";
      return `<div class="person on" title="在地图上跟随" onclick="followPlayer('${esc(p.uuid)}')">
        ${head(p, 30)}
        <div class="who"><span class="name">${esc(p.name)}</span>
          <span class="sub"><i class="dim" style="background:var(--${lp.world.split(":")[1]})"></i>${DIM_NAME[lp.world] || esc(lp.world)} · ${since}</span>
          <span class="vitals" title="生命 ${hp(lp.health)}/20 · 饱食度 ${lp.food}/20">
            <span class="meter hp"><i style="width:${(lp.health / 20) * 100}%"></i></span>${hp(lp.health)}
            <span class="meter food"><i style="width:${(lp.food / 20) * 100}%"></i></span>${lp.food}
          </span></div></div>`;
    }
    return `<div class="person off">${head(p, 30)}<div class="who"><span class="name">${esc(p.name)}</span>
      <span class="sub">${p.last_seen ? fmtAgo(p.last_seen) + "在线" : "离线"}</span></div></div>`;
  });
  setHTML($("#online"), rows.join(""));
}

// Problems the backend found, or the page losing contact with it.
function renderNotice() {
  const msgs = [];
  if (Date.now() - liveOkAt > 60000) msgs.push("无法连接到网站后台，下面的数据可能已经过时。");
  else if (liveResp) {
    const lag = liveResp.now - liveResp.refreshed;
    if (liveResp.refreshed && lag > 300) msgs.push(`数据已 ${fmtDur(lag)}没有更新，后台刷新可能出了问题。`);
    msgs.push(...(liveResp.checks || []));
  }
  const el = $("#notice");
  el.classList.toggle("gone", !msgs.length);
  setHTML(el, msgs.map((m) => `<div>⚠ ${esc(m)}</div>`).join(""));
}

// ---------- server health panel ----------

function toggleHealth() {
  healthOpen = !healthOpen;
  $("#healthpanel").classList.toggle("gone", !healthOpen);
  if (healthOpen) renderHealth();
}

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
  const h = serverHealth();
  if (!h) {
    setHTML(el, `<div class="wrap muted">还没有服务器负载数据（来自 WorldDashboard 插件）。</div>`);
    return;
  }
  const at = liveResp.live.ts / 1000;
  const hist = h.history || [];
  const mem = h.mem_used / h.mem_max;
  const note = healthState() === "idle" ? `<p class="muted">没人在线时服务器会暂停运算，下面是 ${fmtAgo(at)}的数据。</p>` : "";
  setHTML(el, `<div class="wrap">${note}
    <div class="hgrid">
      <div class="hcell"><div class="hk">TPS（1 / 5 / 15 分钟）</div><div class="hv">${h.tps.map((t) => t.toFixed(1)).join(" / ")}</div>
        ${sparkline(hist.map((x) => x.tps), 10, 20, "#8dff6a")}<div class="hn">满分 20，低于 18 会感觉卡</div></div>
      <div class="hcell"><div class="hk">每刻耗时</div><div class="hv">${h.mspt.toFixed(1)} ms</div>
        ${sparkline(hist.map((x) => x.mspt), 0, 60, "#ffcc4d")}<div class="hn">超过 50 ms 就跟不上 20 TPS</div></div>
      <div class="hcell"><div class="hk">内存（Java 堆）</div><div class="hv">${gb(h.mem_used)} / ${gb(h.mem_max)}</div>
        <div class="hbar"><i style="width:${(mem * 100).toFixed(0)}%"></i></div>
        ${sparkline(hist.map((x) => x.mem), 0, h.mem_max, "#62c3ff")}</div>
      <div class="hcell"><div class="hk">CPU</div><div class="hv">服务器 ${h.cpu_process.toFixed(0)}% · 整机 ${h.cpu_system.toFixed(0)}%</div>
        <div class="hn">${h.cores} 核，100% 表示全部核心占满</div>
        <div class="hk" style="margin-top:8px">已加载</div><div class="hv">${num(h.chunks)} 区块 · ${num(h.entities)} 实体</div></div>
    </div>
    <p class="muted hfoot">图表为最近一小时，每分钟一个点。数据更新于 ${fmtAgo(at)}。</p></div>`);
}

// ---------- mainline ----------

function renderProgress() {
  const pr = data.progress;
  const nodes = pr.mainline.map((n) => `<div class="node ${n.ts ? "done" : ""}">
      <span class="frame-ico">${ICON[n.id] ? `<img class="ico" src="assets/tex/${ICON[n.id]}.png" alt="">` : ""}</span>
      <div class="t">${esc(n.title)}</div><div class="d">${esc(n.desc)}</div>
      <div class="when">${n.ts ? "✓ " + fmtDateTime(n.ts) : "未完成"}</div></div>`).join("");
  const pct = pr.total ? (pr.done / pr.total) * 100 : 0;
  const groups = {};
  pr.all.forEach((a) => (groups[a.tab] = groups[a.tab] || []).push(a));
  const all = Object.entries(groups).map(([tab, list]) => {
    const done = list.filter((a) => a.ts).length;
    return `<h3>${TAB_NAME[tab] || esc(tab)} · ${done}/${list.length}</h3>` + list.map((a) => `
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

// ---------- sessions (paged) ----------

async function loadSessions(more = false) {
  const offset = more ? sessions.length : 0;
  const limit = more ? SESSION_PAGE : Math.max(SESSION_PAGE, sessions.length);
  try {
    const page = await getJSON(`api/sessions?offset=${offset}&limit=${limit}`);
    sessions = more ? sessions.concat(page.items) : page.items;
    sessionsTotal = page.total;
    renderSessions();
  } catch (e) {}
}

function renderSessions() {
  if (!data) return;
  const byName = Object.fromEntries(data.players.map((p) => [p.name, p]));
  const cards = sessions.map((s) => {
    const end = s.end ?? now();
    const kind = s.ongoing ? `<span class="tag live">进行中</span>` : s.multi ? `<span class="tag">联机</span>` : `<span class="tag">独自游玩</span>`;
    const ppl = s.players.map((p) => `<span class="pp">${head(byName[p.name], 18)}${esc(p.name)} <span class="muted">${fmtDur(p.secs)}</span></span>`).join("");
    const adv = s.advancements.length ? `<ul class="list">${s.advancements.map((a) => `<li><span class="tm">${fmtTime(a.ts)}</span>${esc(a.name)} 获得成就「${esc(a.title)}」${a.team_first ? ' <span class="first">★ 全队首次</span>' : ""}</li>`).join("")}</ul>` : "";
    let deaths = "";
    if (s.deaths.length) {
      const cnt = {};
      s.deaths.forEach((d) => (cnt[d.name] = (cnt[d.name] || 0) + 1));
      const sum = Object.entries(cnt).sort((a, b) => b[1] - a[1]).map(([n, c]) => `${esc(n)} ×${c}`).join("，");
      const items = s.deaths.map((d) => `<li><span class="tm">${fmtTime(d.ts)}</span>${esc(d.text)}${d.where
        ? `<button class="linkbtn" onclick="showOnMap({dim:'${esc(d.where.dim)}',x:${d.where.pos[0]},z:${d.where.pos[2]},zoom:4})">在地图上看</button>` : ""}</li>`).join("");
      deaths = `<details data-k="d${s.no}"><summary>💀 死亡 ${s.deaths.length} 次：${sum}</summary><ul class="list">${items}</ul></details>`;
    }
    const stats = s.stats ? `<div class="mini">${Object.entries(s.stats).map(([n, v]) => `${esc(n)}：杀怪 ${v.mob_kills} · 挖掘 ${v.mined} · 放置 ${v.placed} · 移动 ${v.km} km${v.diamond_ore ? ` · 钻石矿 ${v.diamond_ore}` : ""}`).join("<br>")}</div>` : "";
    return `<div class="card sess">
      <div class="sess-h"><div><span class="no">第 ${s.no} 次</span>${kind}</div>
        <div class="muted">${fmtDate(s.start)} ${fmtTime(s.start)}–${s.ongoing ? "现在" : fmtTime(end)} · ${fmtDur(end - s.start)}</div></div>
      <div class="headline">${esc(s.headline)}</div>
      <div class="row">${ppl}</div>${adv}${deaths}${stats}</div>`;
  }).join("");
  const more = sessions.length < sessionsTotal
    ? `<button type="button" class="loadmore" onclick="loadSessions(true)">加载更早的记录（还有 ${sessionsTotal - sessions.length} 场）</button>` : "";
  paint($("#tab-sessions"), `<div class="wrap"><h2>联机日志 <span class="muted">· 共 ${sessionsTotal} 场</span></h2>${cards || '<div class="empty">还没有记录</div>'}${more}</div>`);
}

// ---------- players: radar charts and titles ----------

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
  const ps = data.players;
  if (!ps.length) return paint($("#tab-players"), `<div class="wrap"><div class="empty">还没有玩家数据</div></div>`);
  const scores = radarScores();
  const all = radarSVG(ps.map((p, i) => ({ scores: scores[i], color: COLORS[i % 4] })));
  const legend = ps.map((p, i) => `<span style="--c:${COLORS[i % 4]}">${esc(p.name)}</span>`).join("");
  const cards = ps.map((p, i) => {
    const s = p.stats;
    const top = p.causes[0];
    const ld = p.nbt?.last_death;
    const rs = p.nbt?.respawn;
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
    const place = (label, loc) => loc ? `<div class="mini">${label}：${DIM_NAME[loc.dim] || esc(loc.dim)} (${loc.pos.join(", ")})
      <button class="linkbtn" onclick="showOnMap({dim:'${esc(loc.dim)}',x:${loc.pos[0]},z:${loc.pos[2]},zoom:4})">在地图上看</button></div>` : "";
    return `<div class="card pcard">
      <div class="top">${head(p, 48)}<div><div class="nm">${esc(p.name)}</div>
        <div class="ttl">${esc(p.title || "")}</div></div></div>
      ${badges ? `<div class="badges">${badges}</div>` : ""}
      ${radarSVG([{ scores: scores[i], color: COLORS[i % 4] }])}
      <div class="kv">${kv}</div>${place("上次死亡", ld)}${place("重生点", rs)}</div>`;
  }).join("");
  paint($("#tab-players"), `<div class="wrap">
    <div class="sess-h"><h2>玩家</h2>
      <div class="toggle"><button data-m="1" class="${perHour ? "on" : ""}">每小时</button><button data-m="0" class="${perHour ? "" : "on"}">总量</button></div></div>
    <p class="muted" style="margin-top:0">${perHour ? "按每小时游戏时间算，看的是玩法风格。" : "按累计总量算，看的是总贡献。"}每根轴以${ps.length}人中的最高者为满分；「生存」是平均每次死亡之间活了多久。</p>
    <div class="card">${all}<div class="legend">${legend}</div></div>
    <div class="cards">${cards}</div></div>`);
  $("#tab-players").querySelectorAll(".toggle button").forEach((b) => (b.onclick = () => {
    perHour = b.dataset.m === "1";
    renderPlayers();
  }));
}

// ---------- loading ----------

async function loadSummary() {
  try {
    const d = await getJSON("api/summary");
    if (d.loading) return;
    const first = !data;
    const changed = JSON.stringify(d) !== JSON.stringify(data);
    data = d;
    document.title = d.title;
    $("#site-title").textContent = d.title;
    if (changed) {
      renderProgress();
      renderPlayers();
      if (first || sessionsTotal !== d.sessions_total) loadSessions();
      if (window.mapDataChanged) window.mapDataChanged();
    }
    renderStatus();
    if (first) {
      const t = location.hash.slice(1);
      if (["progress", "sessions", "players"].includes(t)) openTab(t);
    }
  } catch (e) {}
}

async function loadLive() {
  try {
    liveResp = await getJSON("api/live");
    liveOkAt = Date.now();
  } catch (e) {}
  renderStatus();
  renderNotice();
  if (healthOpen) renderHealth();
  if (window.mapLive) window.mapLive(livePlayers());
}

loadSummary().then(loadLive);
setInterval(loadSummary, 30000);
setInterval(loadLive, 2000);
setInterval(() => { if (sessions.some((s) => s.ongoing)) loadSessions(); }, 60000);
