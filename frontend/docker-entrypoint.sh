#!/bin/sh
set -eu

# Generate runtime config from the API_BASE env var so the same image can be
# pointed at different control planes without rebuilding.
CONFIG_PATH="/usr/share/nginx/html/config.js"

API_BASE="${API_BASE:-}"

cat > "$CONFIG_PATH" <<EOF
window.__CONFIG__ = window.__CONFIG__ || {};
window.__CONFIG__.API_BASE = "${API_BASE}";
EOF

echo "[entrypoint] wrote ${CONFIG_PATH} with API_BASE='${API_BASE}'"

# When run as a standalone entrypoint (args present), exec them.
# When run by nginx's /docker-entrypoint.d/ init (no args), just return so
# the stock entrypoint continues and starts nginx itself.
if [ "$#" -gt 0 ]; then
  exec "$@"
fi
