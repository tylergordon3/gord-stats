#!/usr/bin/env bash
# One-time setup of fantasy_insights on the Pi. Everything after this is
# `pi deploy fantasy_insights`, plus the daily timer.
#
#   ssh gordpi 'cd ~/apps/fantasy_insights && ./deploy/pi-bootstrap.sh'
set -euo pipefail

UNIT_DIR="$HOME/.config/systemd/user"
cd "$(git rev-parse --show-toplevel)"
log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }

########################################
# PRECONDITIONS
########################################
python3 -m venv --help >/dev/null 2>&1 || {
  echo "❌ python venv missing — run: sudo apt-get install -y python3-venv"; exit 1; }

# The Pi pushes generated pages back, so the remote must use the write-enabled
# deploy key. The github-fantasy alias in ~/.ssh/config points at it.
if ! git remote get-url origin | grep -q '^git@github-fantasy:'; then
  echo "❌ origin must use the github-fantasy alias so pushes use the write key."
  echo "   git remote set-url origin git@github-fantasy:tylergordon3/fantasy_insights.git"
  exit 1
fi

# Commits made by the timer need an identity.
git config user.name  >/dev/null 2>&1 || git config user.name  "gordpi"
git config user.email >/dev/null 2>&1 || git config user.email "tmgordon33@gmail.com"

########################################
# UNITS
########################################
mkdir -p "$UNIT_DIR"
for f in deploy/*.service deploy/*.timer; do
  ln -sfn "$PWD/$f" "$UNIT_DIR/$(basename "$f")"
done
log "units linked into $UNIT_DIR"

# notify@.service is shared across apps and is installed by 1984Bot's bootstrap.
[ -e "$UNIT_DIR/notify@.service" ] || log "⚠️  notify@.service not installed — failure alerts won't fire"

loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now fantasy-rebuild.timer
log "daily rebuild timer armed"

########################################
# FIRST RUN
########################################
exec ./deploy/pi-deploy.sh
