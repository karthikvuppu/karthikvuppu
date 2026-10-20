#!/usr/bin/env bash
# One-shot installer for the Telegram -> Claude -> Gmail/Drive/Browser agent (n8n based).
# Run ON THE SERVER (Ubuntu 22.04/24.04):   chmod +x setup.sh && ./setup.sh
# Secrets are typed here (hidden) and never leave this machine except to their own services.
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ask() { local v; read -r -p "$1${2:+ [$2]}: " v; echo "${v:-${2:-}}"; }
asks() { local v; read -r -s -p "$1: " v; echo >&2; echo "$v"; }
dc() { docker compose "$@"; }

say "1/7 Docker"
if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker..."
  curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null

say "2/7 Your details"
if [ -f .env ]; then
  echo ".env already exists, reusing it (delete it to start over)."
  set -a; . ./.env; set +a
else
  SUB=$(ask "DuckDNS name (the part before .duckdns.org, e.g. karthik-agent)")
  DUCK_TOKEN=$(asks "DuckDNS token (shown on duckdns.org after you log in)")
  TG_IDS=$(ask "Telegram user ID(s) allowed to command the agent" "5814061609")
  N8N_HOST="${SUB}.duckdns.org"

  echo "Pointing ${N8N_HOST} at this server..."
  RES=$(curl -fsS "https://www.duckdns.org/update?domains=${SUB}&token=${DUCK_TOKEN}&ip=" || true)
  [ "$RES" = "OK" ] || { echo "DuckDNS update failed (got: '$RES'). Check the name and token."; exit 1; }
  unset DUCK_TOKEN

  umask 077
  cat > .env <<EOF
N8N_ENCRYPTION_KEY=$(openssl rand -hex 24)
BROWSER_API_KEY=$(openssl rand -hex 24)
BROWSER_APPROVAL_TOKEN=$(openssl rand -hex 24)
TZ=Asia/Kolkata
ALLOWED_TELEGRAM_IDS=${TG_IDS}
N8N_HOST=${N8N_HOST}
EOF
  set -a; . ./.env; set +a
fi

say "3/7 Secrets for n8n credentials (hidden input; press Enter to skip any you will add later in the n8n editor)"
TG_TOKEN=$(asks "Telegram bot token (from @BotFather)")
ANTHROPIC_KEY=$(asks "Anthropic API key")
G_ID=$(ask "Google OAuth client ID (blank to skip)")
G_SECRET=""
[ -n "$G_ID" ] && G_SECRET=$(asks "Google OAuth client secret")

say "4/7 Folders, firewall"
mkdir -p data/n8n data/browser_profile data/caddy
chown -R 1000:1000 data/n8n
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; echo "ufw: opened 80 and 443"
fi
command -v python3 >/dev/null 2>&1 && python3 build_workflows.py >/dev/null

say "5/7 Starting containers (first build takes a few minutes)"
dc up -d --build
echo -n "Waiting for n8n"
for _ in $(seq 1 60); do
  dc exec -T n8n wget -qO- http://localhost:5678/healthz >/dev/null 2>&1 && break
  echo -n "."; sleep 3
done
echo

say "6/7 Importing credentials and workflows"
TG_TOKEN="$TG_TOKEN" ANTHROPIC_KEY="$ANTHROPIC_KEY" G_ID="$G_ID" G_SECRET="$G_SECRET" python3 - <<'PY'
import json, os
e = os.environ
creds = []
def add(cid, name, ctype, data):
    creds.append({"id": cid, "name": name, "type": ctype, "data": data})
if e["TG_TOKEN"]:
    add("agentTelegram01", "Agent Telegram", "telegramApi", {"accessToken": e["TG_TOKEN"], "baseUrl": "https://api.telegram.org"})
if e["ANTHROPIC_KEY"]:
    add("agentAnthropic01", "Agent Anthropic", "anthropicApi", {"apiKey": e["ANTHROPIC_KEY"], "url": "https://api.anthropic.com"})
if e["G_ID"] and e["G_SECRET"]:
    g = {"clientId": e["G_ID"], "clientSecret": e["G_SECRET"]}
    add("agentGmail01", "Agent Gmail", "gmailOAuth2", g)
    add("agentDrive01", "Agent Drive", "googleDriveOAuth2Api", g)
    add("agentDocs01", "Agent Docs", "googleDocsOAuth2Api", g)
if creds:
    p = "data/n8n/creds_tmp.json"
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(creds, f)
PY
if [ -f data/n8n/creds_tmp.json ]; then
  dc exec -T n8n n8n import:credentials --input=/home/node/.n8n/creds_tmp.json
  shred -u data/n8n/creds_tmp.json 2>/dev/null || rm -f data/n8n/creds_tmp.json
fi
unset TG_TOKEN ANTHROPIC_KEY G_ID G_SECRET

dc exec -T n8n n8n import:workflow --input=/workflows/agent-approved-actions.json
GATED_ID=$(dc exec -T n8n n8n list:workflow | tr -d '\r' | awk -F'|' '$2=="Agent - Approved Actions"{print $1}' | tail -1)
[ -n "$GATED_ID" ] || { echo "Could not find the imported sub-workflow id"; exit 1; }
sed "s/__GATED_WORKFLOW_ID__/${GATED_ID}/" workflows/agent-main.json > data/n8n/main_tmp.json
dc exec -T n8n n8n import:workflow --input=/home/node/.n8n/main_tmp.json
rm -f data/n8n/main_tmp.json
dc restart n8n >/dev/null

say "7/7 Done. Remaining steps are yours (about 5 minutes):"
cat <<EOF

 1. On YOUR computer open a terminal and run:
        ssh -L 5678:localhost:5678 <your-user>@<this-server-ip>
    then browse to  http://localhost:5678  and create your n8n owner account.
 2. Google: in Google Cloud Console add this redirect URI to your OAuth client:
        https://${N8N_HOST}/rest/oauth2-credential/callback
    In n8n open Credentials -> Agent Gmail / Agent Drive / Agent Docs -> "Sign in with Google".
 3. Open workflow "Agent - Telegram Assistant" -> toggle it Active (top right).
 4. Message your bot on Telegram: "search my unread emails from today".

Logs:  docker compose logs -f n8n      Stop: docker compose down      Update: docker compose pull && docker compose up -d
EOF
