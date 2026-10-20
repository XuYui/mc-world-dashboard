"""Settings, all from environment variables (see server/dashboard.env.example)."""
import os
from datetime import timedelta, timezone

ENV = os.environ.get
HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_ROOT = os.path.dirname(HERE)                                   # .../server
APP_ROOT = os.path.dirname(SERVER_ROOT)                               # repo root, or the install dir

MC = ENV("DASH_SERVER_DIR", "/opt/minecraft")                         # the Paper server directory
SAVE = ENV("DASH_WORLD", "world")                                     # save folder to report on
TITLE = ENV("DASH_TITLE", SAVE)                                       # name shown on the page
BIND = ENV("DASH_BIND", "0.0.0.0:8123")                               # host:port the web server listens on
WEB = ENV("DASH_WEB_DIR", os.path.join(APP_ROOT, "web"))              # the page (index.html, js, css, assets)
DATA = ENV("DASH_DATA_DIR", os.path.join(APP_ROOT, "state"))          # database, log archive, full maps
DEFS = ENV("DASH_DEFS", os.path.join(SERVER_ROOT, "defs.json"))       # made by tools/build_assets.py
PLUGIN_DIR = ENV("DASH_PLUGIN_DIR", os.path.join(MC, "plugins", "WorldDashboard"))
# Map tiles in squaremap's layout: <dir>/<world>/<zoom>/<x>_<z>.png, 512 px, zoom 3 = 1 block per pixel.
# Any renderer that writes this layout can replace squaremap.
TILES = ENV("DASH_TILE_DIR", os.path.join(MC, "plugins", "squaremap", "web", "tiles"))
TZ = timezone(timedelta(hours=float(ENV("DASH_UTC_OFFSET", "8"))))  # timezone of the server's log timestamps
RESTART = ENV("DASH_RESTART", "04:30")                                # daily restart time shown on the page
REFRESH_SECONDS = int(ENV("DASH_REFRESH", "30"))                      # how often save files are re-read
MERGE_GAP = 15 * 60                                                   # gap between visits that still counts as one session
