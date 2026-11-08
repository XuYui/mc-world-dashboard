"use strict";
// Underground layers and ancient cities on the map (uses map.js's map, mapDim, toLatLng, WORLDS).
// The backend draws a cave tile per region: for a chosen height Y, each column shows the first
// floor below open air within the 32 blocks under Y; solid rock stays dark.

const CAVE_STEP = 8, CAVE_DEPTH = 32;
const CAVE_DIMS = {  // min/max: allowed heights; floor: bottom of the world
  "minecraft:overworld": { min: -56, max: 320, start: -40, floor: -64 },
  "minecraft:the_nether": { min: 8, max: 128, start: 64, floor: 0 },
};
const CAVE_MIN_ZOOM = 2;  // below this a view needs too many tiles drawn on demand

const caveStore = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
};

let caveOn = false;
const caveY = {};
for (const [dim, r] of Object.entries(CAVE_DIMS)) {
  const saved = parseInt(caveStore.get("caveY:" + dim), 10);
  caveY[dim] = Number.isFinite(saved) && saved >= r.min && saved <= r.max && saved % CAVE_STEP === 0 ? saved : r.start;
}

const caveLayer = L.tileLayer("caves/{world}/{layer}/{x}_{y}.png", {
  world: WORLDS["minecraft:overworld"], layer: caveY["minecraft:overworld"], tileSize: TILE,
  minZoom: CAVE_MIN_ZOOM, maxZoom: MAX_ZOOM, minNativeZoom: NATIVE_ZOOM, maxNativeZoom: NATIVE_ZOOM,
  noWrap: true, keepBuffer: 0, className: "pixel", zIndex: 2,
  errorTileUrl: "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==",
});
let caveLoading = false;
caveLayer.on("loading", () => { caveLoading = true; caveNote(); });
caveLayer.on("load", () => { caveLoading = false; caveNote(); });
// A tile still queued for drawing when the request times out keeps rendering on the server;
// ask again a little later (regions that do not exist just fail again, cheaply).
caveLayer.on("tileerror", (e) => {
  const n = (+e.tile.dataset.retry || 0) + 1;
  if (n > 4) return;
  e.tile.dataset.retry = n;
  setTimeout(() => {
    if (e.tile.isConnected) e.tile.src = caveLayer.getTileUrl(e.coords) + "?retry=" + n;
  }, 3000 * n);
});

function caveNote() {
  const note = $("#cavebar .note");
  if (!CAVE_DIMS[mapDim]) note.textContent = "这个维度没有地下层";
  else if (map.getZoom() < CAVE_MIN_ZOOM) note.textContent = "放大一点才显示";
  else if (caveLoading) note.textContent = "绘制中…";
  else note.textContent = `${caveY[mapDim]} ~ ${Math.max(caveY[mapDim] - CAVE_DEPTH + 1, CAVE_DIMS[mapDim].floor)}`;
}

function renderCave() {
  const r = CAVE_DIMS[mapDim];
  $("#cavebar").classList.toggle("gone", !caveOn);
  document.querySelector('#cavebtns [data-cave="layer"]').classList.toggle("on", caveOn);
  if (!caveOn || !r) {
    map.removeLayer(caveLayer);
  } else {
    const y = caveY[mapDim];
    $("#cavebar b").textContent = y;
    $('#cavebar [data-step="1"]').disabled = y >= r.max;
    $('#cavebar [data-step="-1"]').disabled = y <= r.min;
    if (caveLayer.options.world !== WORLDS[mapDim] || caveLayer.options.layer !== y) {
      caveLayer.options.world = WORLDS[mapDim];
      caveLayer.options.layer = y;
      if (map.hasLayer(caveLayer)) caveLayer.redraw();
    }
    if (!map.hasLayer(caveLayer)) caveLayer.addTo(map);
  }
  caveNote();
}

function setCaveY(y) {
  const r = CAVE_DIMS[mapDim];
  if (!r) return;
  caveY[mapDim] = Math.max(r.min, Math.min(r.max, Math.round(y / CAVE_STEP) * CAVE_STEP));
  caveStore.set("caveY:" + mapDim, caveY[mapDim]);
  renderCave();
}

// Holding a step button keeps stepping, but tiles are only requested once the height settles.
let stepTimer = null;
document.querySelectorAll("#cavebar [data-step]").forEach((b) => b.addEventListener("click", () => {
  const r = CAVE_DIMS[mapDim];
  if (!r) return;
  caveY[mapDim] = Math.max(r.min, Math.min(r.max, caveY[mapDim] + CAVE_STEP * +b.dataset.step));
  $("#cavebar b").textContent = caveY[mapDim];
  clearTimeout(stepTimer);
  stepTimer = setTimeout(() => setCaveY(caveY[mapDim]), 450);
}));

document.querySelector('#cavebtns [data-cave="layer"]').addEventListener("click", () => {
  caveOn = !caveOn;
  renderCave();
});
map.on("zoomend", caveNote);
window.caveDimChanged = () => { renderCave(); drawCities(); };

// ---------- ancient cities ----------

let cities = null;
let citiesOn = false;
const cityLayer = L.layerGroup().addTo(map);

// 16x16 pixel-art sculk shrieker-ish marker, drawn here so no game texture is needed.
const CITY_ICON = (() => {
  const rows = ["................", "...cc......cc...", "...cbc....cbc...", "....cbc..cbc....", ".....cbbbbc.....",
    "....cbbttbbc....", "...#bbtggtbb#...", "...#bttggttb#...", "...##########...", "..#ssssssssss#..",
    "..#sddssssdds#..", "..#ssssssssss#..", "..############..", "................", "................", "................"];
  const pal = { "#": "#0b1418", c: "#d9ecd2", b: "#c7d9be", t: "#0d6e72", g: "#2ef0d8", s: "#164a55", d: "#0b2a33" };
  const c = document.createElement("canvas");
  c.width = c.height = 16;
  const g = c.getContext("2d");
  rows.forEach((row, y) => [...row].forEach((ch, x) => {
    if (pal[ch]) { g.fillStyle = pal[ch]; g.fillRect(x, y, 1, 1); }
  }));
  return L.icon({ iconUrl: c.toDataURL(), iconSize: [24, 24], iconAnchor: [12, 12], className: "city" });
})();

// The height whose 32-block window shows the city's buildings and main floor (cities sit on y ≈ -52).
const cityY = (s) => Math.ceil((s.bb[1] + 12) / CAVE_STEP) * CAVE_STEP;

async function loadCities() {
  try { cities = (await getJSON("api/structures")).worlds || {}; } catch (e) { cities = {}; }
}

function citiesHere() {
  return (cities?.[WORLDS[mapDim]] || []).filter((s) => s.id === "minecraft:ancient_city");
}

function goToCity(i) {
  const s = citiesHere()[i];
  if (!s) return;
  stopFollow();
  caveOn = true;
  setCaveY(cityY(s));
  map.setView(toLatLng(s.x, s.z), Math.max(map.getZoom(), NATIVE_ZOOM));
}

function drawCities() {
  cityLayer.clearLayers();
  const list = citiesOn ? citiesHere() : [];
  list.forEach((s, i) => {
    const tip = `<b>古城</b><br>(${s.x}, ${s.bb[1]}, ${s.z}) · 约 ${s.bb[3] - s.bb[0] + 1} × ${s.bb[5] - s.bb[2] + 1} 格<br><span class="muted">点击查看地下层</span>`;
    L.marker(toLatLng(s.x, s.z), { icon: CITY_ICON, zIndexOffset: 500 })
      .bindTooltip(tip, { className: "plate", direction: "top", offset: [0, -12] })
      .on("click", () => goToCity(i)).addTo(cityLayer);
  });
  renderCityList();
}

// The nearest few cities to the middle of the view, so they can be found when off-screen.
function renderCityList() {
  const el = $("#citylist");
  if (!citiesOn) return el.classList.add("gone");
  const c = toBlock(map.getCenter());
  const list = citiesHere().map((s, i) => ({ s, i, d: Math.hypot(s.x - c.x, s.z - c.z) })).sort((a, b) => a.d - b.d).slice(0, 4);
  el.classList.remove("gone");
  if (!CAVE_DIMS[mapDim] || mapDim !== "minecraft:overworld") {
    el.innerHTML = `<div class="hint">古城只在主世界</div>`;
    return;
  }
  if (!list.length) {
    el.innerHTML = `<div class="hint">${cities ? "还没有找到古城" : "加载中…"}</div>`;
    return;
  }
  el.innerHTML = `<div class="hint">最近的古城（共 ${citiesHere().length} 座）</div>` + list.map(({ s, i, d }) =>
    `<button type="button" data-i="${i}">X ${s.x} Z ${s.z}<span class="muted">${d < 1000 ? Math.round(d) + " 格" : (d / 1000).toFixed(1) + " 千格"}</span></button>`).join("");
  el.querySelectorAll("button").forEach((b) => (b.onclick = () => goToCity(+b.dataset.i)));
}
map.on("moveend", () => { if (citiesOn) renderCityList(); });

document.querySelector('#cavebtns [data-cave="cities"]').addEventListener("click", async (e) => {
  citiesOn = !citiesOn;
  e.currentTarget.classList.toggle("on", citiesOn);
  if (citiesOn && !cities) {
    renderCityList();
    await loadCities();
  }
  drawCities();
});
