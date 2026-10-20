// Injected into squaremap's page (map.html) before its bundle runs. squaremap keeps its
// Leaflet map private, so catch it when Leaflet is published on window and expose it to
// the dashboard (same origin) as window.__sqMap.
(function () {
  let real;
  Object.defineProperty(window, "L", {
    configurable: true,
    get() { return real; },
    set(v) {
      real = v;
      try { if (v && v.Map) v.Map.addInitHook(function () { window.__sqMap = this; }); } catch (e) {}
    },
  });
})();
