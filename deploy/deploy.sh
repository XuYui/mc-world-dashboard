#!/usr/bin/env bash
# Install or update the dashboard on the server (and optionally the WorldDashboard plugin).
#
#   cp deploy/config.example deploy/config   # then edit it
#   ./deploy/deploy.sh            # backend + page; restarts only the dashboard, not Minecraft
#   ./deploy/deploy.sh --plugin   # also build the plugin there; it loads on the next server restart
#   NO_START=1 ./deploy/deploy.sh # install without (re)starting the web server
#
# Run tools/build_assets.py first: the game-derived files it makes are not in git.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=/dev/null
source deploy/config

SSH_OPTS=(-o IdentitiesOnly=yes -o ConnectTimeout=15 -o ServerAliveInterval=5)
[[ -n "${SSH_KEY:-}" ]] && SSH_OPTS+=(-i "$SSH_KEY")

for f in server/defs.json web/assets/mcpixel.woff2 web/assets/heads web/assets/skins web/assets/tex; do
    [[ -e $f ]] || { echo "missing $f: run tools/build_assets.py first" >&2; exit 1; }
done
with_plugin=false
[[ ${1:-} == --plugin ]] && with_plugin=true
if $with_plugin && [[ ! -f plugin/build/lang.json ]]; then
    echo "missing plugin/build/lang.json: run tools/build_assets.py first" >&2
    exit 1
fi

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
tar -czf "$tmp/dash.tgz" --exclude='__pycache__' server web
files=(dash.tgz)
if $with_plugin; then
    tar -czf "$tmp/plugin.tgz" --exclude='plugin/build/*.jar' plugin
    files+=(plugin.tgz)
fi
(cd "$tmp" && scp -q "${SSH_OPTS[@]}" "${files[@]}" "$SSH_TARGET:/tmp/")

ssh "${SSH_OPTS[@]}" "$SSH_TARGET" \
    "REMOTE_DIR='$REMOTE_DIR' SERVER_DIR='$SERVER_DIR' RUN_AS='$RUN_AS' WITH_PLUGIN=$with_plugin NO_START='${NO_START:-}' bash -s" <<'EOF'
set -euo pipefail
mkdir -p "$REMOTE_DIR/state"
stage=$(mktemp -d)
tar -xzf /tmp/dash.tgz -C "$stage"
for part in server web; do
    rm -rf "$REMOTE_DIR/$part.old"
    if [[ -d "$REMOTE_DIR/$part" ]]; then mv "$REMOTE_DIR/$part" "$REMOTE_DIR/$part.old"; fi
    mv "$stage/$part" "$REMOTE_DIR/$part"
    rm -rf "$REMOTE_DIR/$part.old"
done
rm -rf "$stage"
[[ -f "$REMOTE_DIR/dashboard.env" ]] || cp "$REMOTE_DIR/server/dashboard.env.example" "$REMOTE_DIR/dashboard.env"
chown -R "$RUN_AS:$RUN_AS" "$REMOTE_DIR"
find "$REMOTE_DIR/server" "$REMOTE_DIR/web" -type d -exec chmod 750 {} +
find "$REMOTE_DIR/server" "$REMOTE_DIR/web" -type f -exec chmod 640 {} +

reload=false
for unit in mc-dashboard-web.service mc-fullmap.service mc-fullmap.timer; do
    sed -e "s|/opt/mc-dashboard|$REMOTE_DIR|g" -e "s|^User=.*|User=$RUN_AS|" -e "s|^Group=.*|Group=$RUN_AS|" \
        "$REMOTE_DIR/server/systemd/$unit" > "/tmp/$unit"
    if ! cmp -s "/tmp/$unit" "/etc/systemd/system/$unit"; then
        mv "/tmp/$unit" "/etc/systemd/system/$unit"
        reload=true
    else
        rm "/tmp/$unit"
    fi
done
if $reload; then systemctl daemon-reload; fi
systemctl enable mc-dashboard-web.service >/dev/null
if [[ ${NO_START:-} != 1 ]]; then systemctl restart mc-dashboard-web.service; fi
if command -v vips >/dev/null; then systemctl enable --now mc-fullmap.timer >/dev/null; fi
echo "dashboard deployed"

if $WITH_PLUGIN; then
    build=$(mktemp -d)
    tar -xzf /tmp/plugin.tgz -C "$build"
    (cd "$build/plugin" && SERVER_DIR="$SERVER_DIR" bash build.sh)
    rm -f "$SERVER_DIR"/plugins/WorldDashboard-[0-9]*.jar
    cp "$build"/plugin/build/WorldDashboard-*.jar "$SERVER_DIR/plugins/"
    mkdir -p "$SERVER_DIR/plugins/WorldDashboard"
    cp "$build/plugin/build/lang.json" "$SERVER_DIR/plugins/WorldDashboard/lang.json"
    chown -R "$RUN_AS:$RUN_AS" "$SERVER_DIR/plugins/WorldDashboard" "$SERVER_DIR"/plugins/WorldDashboard-*.jar
    chmod 750 "$SERVER_DIR/plugins/WorldDashboard"
    chmod 640 "$SERVER_DIR"/plugins/WorldDashboard-*.jar "$SERVER_DIR/plugins/WorldDashboard/lang.json"
    rm -rf "$build"
    echo "plugin installed: it loads on the next server restart"
fi
rm -f /tmp/dash.tgz /tmp/plugin.tgz
EOF
