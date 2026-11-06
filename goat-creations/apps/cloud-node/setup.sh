#!/usr/bin/env bash
# GOAT Cloud: use GOAT CREATIONS from your phone on mobile data, no home computer needed.
#
# Run this on a rented GPU server (Linux, NVIDIA GPU). It installs, on that one machine:
#   1. the GOAT render node (ComfyUI + GOAT pack + open models), private to the machine
#   2. the SEBastina server (owner access, signed result links), private to the machine
#   3. an HTTPS front door: the only thing that faces the internet
# then prints the https:// address and your owner token for the phone app.
#
#   ./setup.sh                      Light models, free Cloudflare https address (changes on restart)
#   ./setup.sh --full | --pro       bigger model sets (24 GB+ GPU; see apps/render-node)
#   ./setup.sh --domain goat.example.com
#                                   your own domain with a free Let's Encrypt certificate (Caddy);
#                                   point the domain's DNS A record at this server and open ports 80 + 443
#   ./setup.sh --dir ~/goat-cloud   where everything goes (default ~/goat-cloud)
#   ./setup.sh --no-start           install only; start later with <dir>/start.sh
# Safe to re-run: installed parts, your token secret and your owner token are kept.
set -euo pipefail

DIR="$HOME/goat-cloud"; MODELS=""; DOMAIN=""; START=1
while [ $# -gt 0 ]; do
  case "$1" in
    --dir) DIR="$2"; shift 2 ;;
    --full) MODELS="--full"; shift ;;
    --pro) MODELS="--pro"; shift ;;
    --domain) DOMAIN="$2"; shift 2 ;;
    --no-start) START=0; shift ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
SERVER="$REPO/apps/server"
COMFY_PORT=8188; SERVER_PORT=8787
NODE_VERSION=22.22.0; CADDY_VERSION=2.10.2
say() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }
mkdir -p "$DIR/bin" "$DIR/run"
DIR="$(cd "$DIR" && pwd)"
case "$(uname -m)" in x86_64) ARCH=amd64; NARCH=x64 ;; aarch64|arm64) ARCH=arm64; NARCH=arm64 ;; *) echo "Unsupported CPU: $(uname -m)"; exit 1 ;; esac
command -v curl >/dev/null || { echo "Please install curl first."; exit 1; }

say "1/4 Render node (private: 127.0.0.1:$COMFY_PORT)"
"$REPO/apps/render-node/setup.sh" --dir "$DIR/render-node" --port "$COMFY_PORT" --private --no-start $MODELS

say "2/4 SEBastina server (private: 127.0.0.1:$SERVER_PORT)"
NODE="$(command -v node || true)"
if [ -z "$NODE" ] || ! "$NODE" -e 'process.exit(+process.versions.node.split(".")[0] >= 20 ? 0 : 1)'; then
  if [ ! -x "$DIR/node/bin/node" ]; then
    echo "Installing Node.js $NODE_VERSION into $DIR/node"
    curl -fsSL "https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-linux-$NARCH.tar.xz" | tar -xJ -C "$DIR"
    rm -rf "$DIR/node"; mv "$DIR/node-v$NODE_VERSION-linux-$NARCH" "$DIR/node"
  fi
  export PATH="$DIR/node/bin:$PATH"
fi
(cd "$REPO" && npm install --no-audit --no-fund --loglevel=error && npx turbo run build --filter=sebastina-server --output-logs=errors-only)

PROFILE=light; [ "$MODELS" = "--full" ] && PROFILE=full; [ "$MODELS" = "--pro" ] && PROFILE=pro
ENV="$SERVER/.env"
[ -f "$ENV" ] || { cp "$SERVER/.env.example" "$ENV"; chmod 600 "$ENV"; }
setenv() { # set KEY=VALUE in .env, replacing the line if it's there
  if grep -q "^$1=" "$ENV"; then sed -i "s#^$1=.*#$1=$2#" "$ENV"; else echo "$1=$2" >> "$ENV"; fi
}
grep -Eq '^SEBASTINA_TOKEN_SECRET=.{32,}' "$ENV" || setenv SEBASTINA_TOKEN_SECRET "$(head -c 48 /dev/urandom | base64 | tr -d '\n/+=')"
setenv PORT "$SERVER_PORT"
setenv HOST 127.0.0.1
setenv TRUST_PROXY 1
setenv SEBASTINA_BACKEND comfyui
setenv COMFYUI_URL "http://127.0.0.1:$COMFY_PORT"
setenv SEBASTINA_LOCAL_PROFILE "$PROFILE"
grep -Eq '^SEBASTINA_OWNERS=.+' "$ENV" || setenv SEBASTINA_OWNERS owner
if [ -n "$DOMAIN" ]; then setenv PUBLIC_ORIGIN "https://$DOMAIN"; fi
OWNER="$(grep '^SEBASTINA_OWNERS=' "$ENV" | cut -d= -f2 | cut -d, -f1)"
TOKEN_FILE="$DIR/owner-token.txt"
if [ ! -s "$TOKEN_FILE" ]; then
  (cd "$SERVER" && node dist/issue-token.js "$OWNER") > "$TOKEN_FILE"
  chmod 600 "$TOKEN_FILE"
fi

say "3/4 HTTPS front door"
if [ -n "$DOMAIN" ]; then
  if [ ! -x "$DIR/bin/caddy" ]; then
    curl -fsSL "https://github.com/caddyserver/caddy/releases/download/v$CADDY_VERSION/caddy_${CADDY_VERSION}_linux_$ARCH.tar.gz" | tar -xz -C "$DIR/bin" caddy
  fi
  printf '%s {\n\treverse_proxy 127.0.0.1:%s\n}\n' "$DOMAIN" "$SERVER_PORT" > "$DIR/Caddyfile"
  echo "Caddy will get a certificate for $DOMAIN (needs its DNS pointed here and ports 80 + 443 open)."
else
  if [ ! -x "$DIR/bin/cloudflared" ]; then
    curl -fsSL -o "$DIR/bin/cloudflared" "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$ARCH"
    chmod +x "$DIR/bin/cloudflared"
  fi
  echo "Cloudflare quick tunnel: a free https address, no account or open ports needed."
fi

# start.sh starts (or restarts) all three parts; run it again after a reboot.
GPU_FLAG=""; command -v nvidia-smi >/dev/null && nvidia-smi >/dev/null 2>&1 || GPU_FLAG="--cpu"
cat > "$DIR/start.sh" <<EOF
#!/usr/bin/env bash
# Start GOAT Cloud: render node, SEBastina server and the HTTPS front door.
set -euo pipefail
export PATH="$DIR/node/bin:\$PATH"
cd "$DIR/run"
for p in comfyui server door; do [ -f \$p.pid ] && kill "\$(cat \$p.pid)" 2>/dev/null || true; done
sleep 1
# Each part runs fully detached (own log, no terminal); its real process id is kept for restarts.
launch() { local name="\$1" dir="\$2"; shift 2; (cd "\$dir" && exec nohup "\$@" > "$DIR/run/\$name.log" 2>&1 < /dev/null) & echo \$! > "$DIR/run/\$name.pid"; }
launch comfyui "$DIR/render-node/ComfyUI" "$DIR/render-node/venv/bin/python" main.py --listen 127.0.0.1 --port $COMFY_PORT --disable-auto-launch $GPU_FLAG
launch server "$SERVER" node dist/index.js
rm -f "$DIR/run/address.txt"
EOF
if [ -n "$DOMAIN" ]; then
  cat >> "$DIR/start.sh" <<EOF
launch door "$DIR" "$DIR/bin/caddy" run --config "$DIR/Caddyfile" --adapter caddyfile
echo "https://$DOMAIN" > "$DIR/run/address.txt"
EOF
else
  cat >> "$DIR/start.sh" <<EOF
launch door "$DIR" "$DIR/bin/cloudflared" tunnel --no-autoupdate --url http://127.0.0.1:$SERVER_PORT
for i in \$(seq 1 60); do
  url="\$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$DIR/run/door.log" | head -1 || true)"
  if [ -n "\$url" ] && grep -q 'Registered tunnel connection' "$DIR/run/door.log"; then echo "\$url" > "$DIR/run/address.txt"; break; fi
  kill -0 "\$(cat "$DIR/run/door.pid")" 2>/dev/null || { echo "The Cloudflare tunnel stopped: see $DIR/run/door.log (does this server allow outbound connections?)"; break; }
  sleep 1
done
EOF
fi
cat >> "$DIR/start.sh" <<EOF
for i in \$(seq 1 120); do curl -fs -o /dev/null http://127.0.0.1:$SERVER_PORT/health && break; sleep 1; done
curl -fs -o /dev/null http://127.0.0.1:$SERVER_PORT/health || echo "The SEBastina server did not start: see $DIR/run/server.log"
echo "GOAT Cloud is running. Phone address: \$(cat "$DIR/run/address.txt" 2>/dev/null || echo 'not ready yet, see $DIR/run/door.log')"
EOF
chmod +x "$DIR/start.sh"

say "4/4 Ready"
if [ "$START" = 1 ]; then "$DIR/start.sh"; else echo "Start it with: $DIR/start.sh"; fi
ADDRESS="$(cat "$DIR/run/address.txt" 2>/dev/null || echo '(run start.sh to get it)')"
cat <<EOF

On your phone (Wi-Fi or mobile data):
  GOAT CREATIONS > Settings > GOAT Cloud
  Server address: $ADDRESS
  Access token:   cat $TOKEN_FILE     (type or copy it into the app; never post it anywhere)
  Tap Save and test.

Only the https address faces the internet. ComfyUI and the server listen on 127.0.0.1 only.
EOF
[ -n "$DOMAIN" ] || echo "The free Cloudflare address changes each time start.sh runs; use --domain for a permanent one."
echo "Logs: $DIR/run/*.log   Restart after a reboot: $DIR/start.sh"
