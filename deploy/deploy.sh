#!/usr/bin/env bash
# Upload the dashboard (and optionally build + install the DeathMarkers plugin) on the server.
#
#   cp deploy/config.example deploy/config   # then edit it
#   ./deploy/deploy.sh            # dashboard only: no server restart needed
#   ./deploy/deploy.sh --plugin   # also build the plugin there; it loads on the next server restart
#
# Run tools/build_assets.py first: the game-derived files it makes are not in git.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=/dev/null
source deploy/config

SSH_OPTS=(-o IdentitiesOnly=yes -o ConnectTimeout=15 -o ServerAliveInterval=5)
[[ -n "${SSH_KEY:-}" ]] && SSH_OPTS+=(-i "$SSH_KEY")
remote() { ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "$@"; }

for f in dashboard/defs.json dashboard/static/mcpixel.woff2 dashboard/static/heads; do
    [[ -e $f ]] || { echo "missing $f: run tools/build_assets.py first" >&2; exit 1; }
done

with_plugin=false
[[ ${1:-} == --plugin ]] && with_plugin=true

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
tar -czf "$tmp/dash.tgz" -C dashboard gen.py seed_graves.py defs.json dashboard.env.example static systemd
files=(dash.tgz)
if $with_plugin; then
    [[ -f plugin/build/lang.json ]] || { echo "missing plugin/build/lang.json: run tools/build_assets.py" >&2; exit 1; }
    tar -czf "$tmp/plugin.tgz" plugin/src plugin/build.sh plugin/build/lang.json
    files+=(plugin.tgz)
fi
(cd "$tmp" && scp -q "${SSH_OPTS[@]}" "${files[@]}" "$SSH_TARGET:/tmp/")

remote "REMOTE_DIR='$REMOTE_DIR' SERVER_DIR='$SERVER_DIR' RUN_AS='$RUN_AS' WITH_PLUGIN=$with_plugin bash -s" <<'EOF'
set -euo pipefail
mkdir -p "$REMOTE_DIR/state"
rm -rf "$REMOTE_DIR/static.new"
tar -xzf /tmp/dash.tgz -C "$REMOTE_DIR" --transform 's,^static,static.new,'
rm -rf "$REMOTE_DIR/static" && mv "$REMOTE_DIR/static.new" "$REMOTE_DIR/static"
for unit in mc-dashboard.service mc-dashboard.timer; do
    if ! cmp -s "$REMOTE_DIR/systemd/$unit" "/etc/systemd/system/$unit"; then
        cp "$REMOTE_DIR/systemd/$unit" /etc/systemd/system/
        systemctl daemon-reload
    fi
done
chown -R "$RUN_AS:$RUN_AS" "$REMOTE_DIR"
find "$REMOTE_DIR" -type d -exec chmod 750 {} + && find "$REMOTE_DIR" -type f -exec chmod 640 {} +
systemctl enable --now mc-dashboard.timer >/dev/null
systemctl start mc-dashboard.service
echo "dashboard deployed"

if $WITH_PLUGIN; then
    build=$(mktemp -d)
    tar -xzf /tmp/plugin.tgz -C "$build"
    (cd "$build/plugin" && SERVER_DIR="$SERVER_DIR" bash build.sh)
    rm -f "$SERVER_DIR"/plugins/DeathMarkers-*.jar
    cp "$build"/plugin/build/DeathMarkers-*.jar "$SERVER_DIR/plugins/"
    mkdir -p "$SERVER_DIR/plugins/DeathMarkers"
    cp "$build/plugin/build/lang.json" "$SERVER_DIR/plugins/DeathMarkers/lang.json"
    chown -R "$RUN_AS:$RUN_AS" "$SERVER_DIR/plugins/DeathMarkers" "$SERVER_DIR"/plugins/DeathMarkers-*.jar
    chmod 750 "$SERVER_DIR/plugins/DeathMarkers"
    chmod 640 "$SERVER_DIR"/plugins/DeathMarkers-*.jar "$SERVER_DIR/plugins/DeathMarkers/lang.json"
    if [[ ! -e "$SERVER_DIR/plugins/DeathMarkers/deaths.json" ]]; then
        # first install: start from the deaths the dashboard could already place
        sudo -u "$RUN_AS" env PYTHONDONTWRITEBYTECODE=1 $(grep -v '^#' "$REMOTE_DIR/dashboard.env" 2>/dev/null | xargs)             python3 "$REMOTE_DIR/seed_graves.py" "$SERVER_DIR/plugins/DeathMarkers/deaths.json" || true
    fi
    rm -rf "$build"
    echo "plugin installed: loads on the next server restart"
fi
rm -f /tmp/dash.tgz /tmp/plugin.tgz
EOF
