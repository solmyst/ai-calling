#!/usr/bin/env bash
# Start (or restart) the bot as a service behind HTTPS.
#
#   bash start.sh                 # public name = <vm-ip>.sslip.io (no domain needed)
#   bash start.sh 859623          # every call looks up proposal 859623
#   PUBLIC_HOST=bot.example.com bash start.sh
#
# Then open https://<PUBLIC_HOST>/ in Chrome, allow the mic, press Connect.
set -euo pipefail
DIR=/opt/ai-calling
IP="$(curl -fsS https://api.ipify.org)"
PUBLIC_HOST="${PUBLIC_HOST:-${IP//./-}.sslip.io}"
PROPOSAL_FLAG="${1:+--proposal $1}"
[ -f "$DIR/voicebot/server/.env" ] || { echo "missing $DIR/voicebot/server/.env"; exit 1; }

sed -e "s|__USER__|$USER|g" -e "s|__PUBLIC_HOST__|$PUBLIC_HOST|g" -e "s|__HOME__|$HOME|g" \
  -e "s|__EXTRA__|$PROPOSAL_FLAG|g" \
  "$DIR/voicebot/deploy/voicebot.service" | sudo tee /etc/systemd/system/voicebot.service >/dev/null
sed -e "s|__PUBLIC_HOST__|$PUBLIC_HOST|g" "$DIR/voicebot/deploy/Caddyfile" | sudo tee /etc/caddy/Caddyfile >/dev/null

sudo systemctl daemon-reload
sudo systemctl enable -q --now voicebot && sudo systemctl restart voicebot
sudo systemctl reload caddy || sudo systemctl restart caddy

echo "Open in Chrome: https://$PUBLIC_HOST/   (allow mic, press Connect)"
echo "If Connect hangs: open UDP 1024-65535 inbound in the VM firewall / security group."
echo "Logs:         tail -f $DIR/voicebot/server/call.log"
