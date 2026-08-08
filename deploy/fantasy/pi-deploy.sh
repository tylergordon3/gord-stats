#!/usr/bin/env bash
# Rebuild the site on the Pi and publish it. Run daily by fantasy-rebuild.timer,
# and on demand from the laptop with `pi deploy fantasy_insights`.
#
# There's no long-running service here — the "deploy" and the daily data job are
# the same thing: pull the latest code, regenerate the pages, push the result.
# GitHub Pages builds the Jekyll site from docs/, so nothing is built here.
set -euo pipefail

# Body lives in main() because this script git-pulls a newer copy of itself
# partway through, and bash reads scripts lazily by byte offset.
main() {
  cd "$(git rev-parse --show-toplevel)"

  local VENV="$PWD/.venv"
  local PRESET="${PRESET:-predraft}"
  export MPLBACKEND="${MPLBACKEND:-Agg}"

  ########################################
  # PULL
  ########################################
  local BRANCH BEFORE AFTER
  BRANCH="$(git branch --show-current)"
  BEFORE="$(git rev-parse HEAD)"

  git fetch --quiet origin "$BRANCH"
  # The Pi commits generated pages, so it can legitimately be ahead of origin.
  # Rebase keeps those on top rather than creating a merge commit every day.
  git pull --rebase --quiet origin "$BRANCH"
  AFTER="$(git rev-parse HEAD)"

  if [ "$BEFORE" = "$AFTER" ]; then
    log "already at $(git rev-parse --short HEAD)"
  else
    log "$(git rev-parse --short "$BEFORE") -> $(git rev-parse --short "$AFTER")"
  fi

  ########################################
  # PYTHON ENVIRONMENT
  ########################################
  [ -d "$VENV" ] || { log "creating venv"; python3 -m venv "$VENV"; }
  # shellcheck source=/dev/null
  . "$VENV/bin/activate"

  if [ "$BEFORE" != "$AFTER" ] && ! git diff --quiet "$BEFORE" "$AFTER" -- requirements-pi.txt; then
    log "requirements changed — reinstalling"
    pip install -q --upgrade pip
    pip install -q -r requirements-pi.txt
  elif ! python -c "import nflreadpy, polars, pandas" 2>/dev/null; then
    log "installing dependencies (first run)"
    pip install -q --upgrade pip
    pip install -q -r requirements-pi.txt
  else
    log "dependencies unchanged"
  fi

  ########################################
  # REBUILD
  ########################################
  log "running rebuild.py --preset $PRESET"
  python rebuild.py --preset "$PRESET" --yes

  ########################################
  # PUBLISH
  ########################################
  # docs/_site and data/players are gitignored, so this only picks up the
  # generated pages and the stored datasets that are meant to be tracked.
  git add -A docs data

  if git diff --cached --quiet; then
    log "no changes to publish"
    return 0
  fi

  log "$(git diff --cached --numstat | wc -l) file(s) changed"
  git commit -q -m "Daily rebuild ($PRESET) $(date '+%Y-%m-%d %H:%M')"

  # Someone may have pushed from the laptop while this was running; rebase onto
  # them and retry rather than failing a whole day's run on a race.
  if ! git push --quiet origin "$BRANCH" 2>/dev/null; then
    log "push rejected — rebasing onto origin and retrying"
    git pull --rebase --quiet origin "$BRANCH"
    git push --quiet origin "$BRANCH"
  fi

  log "✅ published $(git rev-parse --short HEAD) — GitHub Pages will rebuild"
}

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }

main "$@"
