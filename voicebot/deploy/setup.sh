#!/usr/bin/env bash
# One-time setup of the voice bot on a fresh Ubuntu 22.04 / 24.04 VM.
#
#   ssh -A <user>@<vm-ip>          # -A: forwards your SSH key so the VM can clone
#   curl -fsSL <this file> | bash  # or copy it over and: bash setup.sh
#
# Then copy your .env to /opt/ai-calling/voicebot/server/.env and run
# deploy/start.sh. Nothing here needs editing.
set -euo pipefail

REPO="${REPO:-git@bitbucket.org:ovunque/ai-calling-agent.git}"
BRANCH="${BRANCH:-insurance}"
DIR=/opt/ai-calling

sudo apt-get update -qq
sudo apt-get install -y -qq git curl debian-keyring debian-archive-keyring apt-transport-https

# Caddy: HTTPS in front of the bot, certificate issued and renewed by itself.
if ! command -v caddy >/dev/null; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update -qq && sudo apt-get install -y -qq caddy
fi

# uv: installs the right Python and the exact package versions in uv.lock.
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

ssh-keyscan -q bitbucket.org >> ~/.ssh/known_hosts 2>/dev/null || true
sudo mkdir -p "$DIR" && sudo chown "$USER" "$DIR"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch -q origin "$BRANCH" && git -C "$DIR" checkout -q "$BRANCH" && git -C "$DIR" pull -q --ff-only
else
  git clone -q -b "$BRANCH" "$REPO" "$DIR"
fi

cd "$DIR/voicebot/server" && uv sync --frozen
echo "Setup done. Next: copy .env to $DIR/voicebot/server/.env, then run: bash $DIR/voicebot/deploy/start.sh"
