#!/usr/bin/env bash
# Frequent WNBA refresh while games are being played. Run every 10 minutes by
# wnba-live.timer, and on demand with `deploy/pi-live.sh`.
#
# The gate is one ESPN scoreboard call: if no WNBA game is live (or tipping
# within 30 minutes) the tick exits in about a second. When games are on, it
# refetches fantasy data, rebuilds the site, and republishes via wrangler —
# the same direct-upload path as pi-deploy.sh. Git gets a commit at most once
# an hour: publishing doesn't need git, commits are for the laptop to pull.
#
# It does pull, though. The tick rebuilds and republishes the whole site, so a
# tick running from a stale checkout republishes a stale site.
set -euo pipefail

main() {
  cd "$(git rev-parse --show-toplevel)"

  local VENV="$PWD/.venv"
  local PROJECT="${CF_PAGES_PROJECT:-gordstats-cbb}"
  export MPLBACKEND="${MPLBACKEND:-Agg}"

  # Don't fight the daily deploy for the repo or the Pi's cores.
  if systemctl --user is-active --quiet gordstats-daily.service 2>/dev/null; then
    log "gordstats-daily is running — skipping this tick"
    exit 0
  fi

  ########################################
  # SECRETS (same contract as pi-deploy.sh)
  ########################################
  local SECRETS="$HOME/secrets/gord-stats.env"
  [ -f "$SECRETS" ] || { echo "❌ no secrets at $SECRETS"; exit 1; }
  set -o allexport
  # shellcheck source=/dev/null
  . "$SECRETS"
  set +o allexport

  ########################################
  # PULL
  ########################################
  # This tick publishes the whole site, not just the WNBA panel, so it has to
  # be building from the current source. Without this it built from whatever
  # the checkout happened to be and published that over the top of anything
  # newer: on 2026-08-19 the 19:00 tick republished the site as it stood before
  # that afternoon's work, minutes after that work had been deployed by hand.
  #
  # Ticks regenerate docs/ and data/ but only commit hourly, so the tree is
  # usually dirty here and a rebase would refuse to start. Discarding is safe —
  # everything under those paths is generated, and the gate below regenerates
  # what this tick needs.
  local BRANCH
  BRANCH="$(git branch --show-current)"
  if ! git diff --quiet -- docs data; then
    git checkout -- docs data
  fi
  if git diff --quiet && git diff --cached --quiet; then
    git fetch --quiet origin "$BRANCH"
    if ! git merge-base --is-ancestor "origin/$BRANCH" HEAD; then
      log "origin moved — rebasing before rebuild"
      git pull --rebase --quiet origin "$BRANCH" || {
        git rebase --abort 2>/dev/null || true
        log "⚠️ rebase failed — skipping this tick rather than publishing stale"
        exit 0
      }
    fi
  else
    # Something outside docs/ and data/ is uncommitted, which is not this
    # script's to resolve. Publishing from it would be publishing a mystery.
    log "⚠️ uncommitted changes outside docs/ and data/ — skipping this tick"
    git status --short
    exit 0
  fi

  ########################################
  # GATE + REGENERATE
  ########################################
  # shellcheck source=/dev/null
  . "$VENV/bin/activate"

  local RC=0
  python -m wnba.wnba_live || RC=$?
  if [ "$RC" -eq 3 ]; then
    exit 0                       # no active games — quiet tick
  elif [ "$RC" -ne 0 ]; then
    echo "❌ live refresh failed (rc=$RC)"
    exit "$RC"
  fi

  ########################################
  # BUILD + PUBLISH
  ########################################
  export PATH="$HOME/.local/share/gem/ruby/3.3.0/bin:$HOME/gems/bin:$PATH"
  export BUNDLE_PATH="vendor/bundle"
  export BUNDLE_WITHOUT="development:test"

  log "jekyll build"
  bundle exec jekyll build --source docs --destination docs/_site --quiet

  log "deploying to Cloudflare Pages ($PROJECT)"
  wrangler pages deploy docs/_site --project-name="$PROJECT" --commit-dirty=true >/dev/null

  ########################################
  # HOURLY COMMIT
  ########################################
  local STAMP="$PWD/.last_live_commit" NOW LAST=0
  NOW=$(date +%s)
  [ -f "$STAMP" ] && LAST=$(stat -c %Y "$STAMP")

  if [ $((NOW - LAST)) -ge 3600 ]; then
    git add -A docs data
    if git diff --cached --quiet; then
      log "no data changes to record"
    else
      git commit -q -m "Live update (wnba) $(date '+%Y-%m-%d %H:%M')"
      if ! git push --quiet origin "$BRANCH" 2>/dev/null; then
        log "push rejected — rebasing onto origin and retrying"
        if git pull --rebase --quiet origin "$BRANCH"; then
          git push --quiet origin "$BRANCH" || log "⚠️ push still failing — will retry next hour"
        else
          git rebase --abort || true
          log "⚠️ rebase failed — leaving commit local, will retry next hour"
        fi
      fi
      log "recorded $(git rev-parse --short HEAD)"
    fi
    touch "$STAMP"
  fi

  log "✅ live tick done"
}

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }

main "$@"
