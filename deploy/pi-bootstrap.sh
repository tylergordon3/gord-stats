#!/usr/bin/env bash
# One-time setup of cbb-model on the Pi. Afterwards it's `pi deploy cbb-model`
# plus the daily timer.
#
#   ssh gordpi 'cd ~/apps/cbb-model && ./deploy/pi-bootstrap.sh'
set -euo pipefail

UNIT_DIR="$HOME/.config/systemd/user"
SECRETS="$HOME/secrets/cbb-model.env"
cd "$(git rev-parse --show-toplevel)"
log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }

########################################
# PRECONDITIONS
########################################
python3 -m venv --help >/dev/null 2>&1 || {
  echo "❌ python venv missing — sudo apt-get install -y python3-venv"; exit 1; }

export PATH="$HOME/.local/share/gem/ruby/3.3.0/bin:$PATH"
command -v ruby   >/dev/null || { echo "❌ ruby missing — sudo apt-get install -y ruby-full ruby-dev"; exit 1; }
command -v bundle >/dev/null || { echo "❌ bundler missing — gem install --user-install bundler -v 2.7.2"; exit 1; }
command -v wrangler >/dev/null || { echo "❌ wrangler missing — sudo npm install -g wrangler"; exit 1; }

[ -f "$SECRETS" ] || { echo "❌ no secrets at $SECRETS"; exit 1; }
grep -q '^CLOUDFLARE_API_TOKEN=' "$SECRETS" || {
  echo "❌ CLOUDFLARE_API_TOKEN missing from $SECRETS."
  echo "   wrangler on your laptop is authenticated interactively via OAuth,"
  echo "   which can't work here. Create an API token with the"
  echo "   'Cloudflare Pages: Edit' permission and add it to that file."
  exit 1; }

# Which sections the daily job refreshes. Only WNBA is automated today.
grep -q '^CBB_TASKS=' "$SECRETS" || {
  echo 'CBB_TASKS=wnba' >> "$SECRETS"
  log "defaulted CBB_TASKS=wnba in $SECRETS"; }

# The Pi records generated data back to the repo, so it needs a push identity
# and a write-enabled remote.
if ! git remote get-url origin | grep -q '^git@github-cbb:'; then
  echo "❌ origin must use the github-cbb alias so pushes use the write key."
  echo "   git remote set-url origin git@github-cbb:tylergordon3/cbb-model.git"
  exit 1
fi
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

[ -e "$UNIT_DIR/notify@.service" ] || log "⚠️  notify@.service not installed — failure alerts won't fire"

loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now cbb-daily.timer
log "daily timer armed"

########################################
# FIRST RUN
########################################
exec ./deploy/pi-deploy.sh
