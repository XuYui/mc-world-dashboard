# mc-world-dashboard

[中文](README.md)

A web dashboard for small Minecraft (Paper) servers: see the map, who is online, how far the group has got, what happened in each play session and how everyone plays, without opening the game.

It is a small standalone site. A Paper plugin reports events and live state; a backend written with nothing but the Python standard library combines them with the save files and server logs and serves the page. Map tiles are the images rendered by [squaremap](https://github.com/jpenilla/squaremap), but the map UI and everything else are this project's own, and any renderer that writes the same tile layout can replace squaremap.

The interface text is Chinese. Game names (advancements, mobs, death messages) come from the game's own language files, generated from your client in the language you pick, so the most visible strings follow that choice.

## Features

- **Map**: a Leaflet map with overworld / nether / end; online players live on the map; click a head to follow a player (keeps following through zoom and drag, switches dimension through portals); block coordinates under the cursor.
- **Gravestones**: two mutually exclusive layers, latest death per player (with a clickable list) and every recorded death; hover for the death message and time.
- **Map export**: stitch the current view or the whole explored area into a PNG at a chosen scale, with an optional caption. The full-resolution image of a whole dimension is too big for a browser, so the server stitches it daily with libvips for direct download.
- **Status bar**: server up or down, who is online (dimension, health, hunger, time online), in-game day, day/night, weather and TPS. Click TPS for memory, CPU, loaded chunks and entities, with an hour of history.
- **Mainline**: ten key advancements from the first stone to the ender dragon, with when the group first achieved each, plus the full advancement list.
- **Sessions**: play sessions are split automatically. Each shows who played, for how long, new advancements (team firsts marked) and deaths (jump to the spot on the map). Sessions load in pages.
- **Players**: a six-axis radar chart (per hour or totals), about 55 automatic titles (each with its reason), last death point and respawn point.
- Block-texture look with the game's pixel font for headings and numbers; works on phones and tablets. The site checks itself and shows a notice if the plugin's data, the tiles or its own refresh stop working.

## How it fits together

```
Paper server
 ├─ plugin/  WorldDashboard: events.jsonl (joins, quits, deaths with position, start/stop)
 │                           live.json    (online players, TPS, memory, CPU, every 2 s)
 └─ squaremap (only renders tiles: tiles/<world>/<zoom>/<x>_<z>.png)
                 │
server/mcdash  backend (Python stdlib + SQLite)
 ├─ stores events; history from before the plugin is imported from server logs
 ├─ reads the save: stats, advancements, player data, clock and weather (cached by mtime)
 ├─ /api/summary  /api/sessions  /api/live  /api/graves  /api/tiles
 ├─ /tiles/…  /heads/<uuid>.png  /fullmap/<world>.png  and the page itself
 └─ fullmap.py: stitches full-resolution images daily (needs vips)
                 │
web/  the page (no framework, no build step; Leaflet 1.9.4 included, BSD-2)
```

The backend refreshes every 30 s. Responses carry ETags and are gzipped, so an unchanged response costs a 304. The site stays up while Minecraft is down.

## Requirements

- Paper 26.1.x (tested on 26.1.2) and squaremap (only for tiles; its own web server can be turned off)
- Server: Linux with systemd and Python 3.9+. JDK 25 to compile the plugin. Optionally the `vips` command for full-resolution maps (`apt install --no-install-recommends libvips-tools`)
- A computer with the same Minecraft client version, to generate the game assets (below)
- Online or offline mode; in offline mode heads use the default skin the game assigns to each UUID

## Game assets (important)

Block textures, default skins, language files and the bitmap font belong to Mojang, so **this repository contains no game assets**. Generate them from your own client:

```bash
pip install pillow fonttools brotli
python tools/build_assets.py --minecraft ~/.minecraft --version 26.1.2 --lang en_us
```

This writes `server/defs.json`, `web/assets/` (textures, heads, pixel font) and `plugin/build/lang.json`, all git-ignored. The CJK part of the pixel font comes from GNU Unifont, which ships with the game (SIL OFL 1.1).

## Install

1. Generate the game assets (above).
2. `cp deploy/config.example deploy/config` and fill in the SSH target, install directory, server directory and the user the server runs as.
3. Run `./deploy/deploy.sh --plugin`. It uploads the backend and page, installs the systemd service `mc-dashboard-web` and the daily `mc-fullmap.timer`, and builds and installs the plugin on the server. The plugin loads on the next Minecraft restart.
4. Edit `/opt/mc-dashboard/dashboard.env` on the server (copied from [server/dashboard.env.example](server/dashboard.env.example)). Set at least `DASH_WORLD`, the save folder name, then run `systemctl restart mc-dashboard-web`.
5. The site listens on port 8123 by default. If squaremap's built-in web server also uses 8123, set `internal-webserver.enabled: false` in its `config.yml`; tiles keep rendering.

Later updates are just `./deploy/deploy.sh`, with no Minecraft restart. For a domain with HTTPS, put nginx in front: see [deploy/nginx.conf.example](deploy/nginx.conf.example).

## Development

- Backend tests: `cd server && python -m unittest discover -s tests`
- Build the plugin: `SERVER_DIR=/opt/minecraft ./plugin/build.sh` (compiles against the server's own libraries, no Gradle)
- Prebuilt plugin jars are on the [Releases](../../releases) page.

## Privacy

Server logs contain player IP addresses, and plugins such as AuthMe store them too. The backend only takes parsed events (joins, quits, deaths) and never puts raw log lines or IPs into the page's data. The page has no login: anyone with the address can see the map, coordinates and when people play, so add access control if you need it.

## License

MIT, see [LICENSE](LICENSE). Leaflet is BSD-2-Clause (`web/vendor/leaflet/LICENSE`). Minecraft is a trademark of Mojang AB; this project is not affiliated with Mojang or Microsoft.
