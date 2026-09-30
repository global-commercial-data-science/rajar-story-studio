#!/usr/bin/env bash
# Serve RAJAR Pulse to colleagues on the same wifi / office network.
#
#   ./app/serve_lan.sh            HTTP  on port 8000
#   ./app/serve_lan.sh --https    HTTPS on port 8443 (self-signed certificate), for networks that block plain HTTP
#
# A passcode is always required on the network. Set APP_PASSCODE to choose it, otherwise one is generated.
# Colleagues open the printed URL; the browser asks for a username (anything) and the passcode.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PY:-$HOME/opt/anaconda3/envs/aiEnv/bin/python}"
HTTPS=0
[ "${1:-}" = "--https" ] && HTTPS=1
PORT="${PORT:-$([ $HTTPS = 1 ] && echo 8443 || echo 8000)}"

# Build the frontend once
if [ ! -d app/frontend/dist ] || [ "${REBUILD:-0}" = "1" ]; then
  (cd app/frontend && npm install --no-audit --no-fund && npm run build)
fi

IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || true)"
HOST="$(scutil --get LocalHostName 2>/dev/null || hostname -s).local"
[ -z "$IP" ] && { echo "No network address found. Are you connected to wifi?"; exit 1; }

export APP_PASSCODE="${APP_PASSCODE:-$(LC_ALL=C tr -dc 'a-z0-9' </dev/urandom | head -c 8)}"

SSL_ARGS=()
SCHEME=http
if [ $HTTPS = 1 ]; then
  SCHEME=https
  CERT_DIR=app/.certs
  mkdir -p "$CERT_DIR"
  if [ ! -f "$CERT_DIR/cert.pem" ] || ! openssl x509 -in "$CERT_DIR/cert.pem" -noout -text | grep -q "IP Address:$IP"; then
    echo "Creating a self-signed certificate for ${IP} and ${HOST}..."
    openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj "/CN=RAJAR Pulse" \
      -keyout "$CERT_DIR/key.pem" -out "$CERT_DIR/cert.pem" \
      -addext "subjectAltName=IP:$IP,DNS:$HOST,DNS:localhost,IP:127.0.0.1" 2>/dev/null
    chmod 600 "$CERT_DIR/key.pem"
  fi
  SSL_ARGS=(--ssl-keyfile "$CERT_DIR/key.pem" --ssl-certfile "$CERT_DIR/cert.pem")
fi

cat <<EOF

  RAJAR Pulse is being served on your network

    ${SCHEME}://${IP}:${PORT}
    ${SCHEME}://${HOST}:${PORT}

  Passcode: ${APP_PASSCODE}   (username: anything)
$([ $HTTPS = 1 ] && echo "  The certificate is self-signed: colleagues click 'Advanced' → 'Proceed' the first time.")
  If macOS asks whether Python may accept incoming connections, choose Allow.
  Press Ctrl+C to stop.

EOF

exec "$PY" -m uvicorn app.backend.main:app --host 0.0.0.0 --port "$PORT" ${SSL_ARGS[@]+"${SSL_ARGS[@]}"}
