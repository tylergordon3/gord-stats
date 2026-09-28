#!/usr/bin/env bash
# Frequent refresh while something is happening. Run every 10 minutes by
# wnba-live.timer, and on demand with `deploy/pi-live.sh`.
#
# Three gates, each a call or two: the WNBA scoreboard (a game live or tipping
# within 30 minutes), the CFB scoreboard (same window — see cfb.live) and the
# fantasy section (a week of the season fully
# scored — see fantasy.live). If none has anything, the
# tick exits in about a second. Otherwise whichever fired regenerates its
# pages and the tick rebuilds the site and republishes via wrangler — the same
# direct-upload path as pi-deploy.sh. Git gets a commit at most once an hour
# for WNBA ticks, and immediately when fantasy fires, since those are rare and
# the power rankings archive a snapshot that should be recorded: publishing
# doesn't need git, commits are for the PC to pull.
#
# It does pull, though. The tick rebuilds and republishes the whole site, so a
# tick running from a stale checkout republishes a stale site.
set -euo pipefail

main() {
  cd "$(git rev-parse --show-toplevel)"

  local VENV="$PWD/.venv"
  local PROJECT="${CF_PAGES_PROJECT:-gordstats-cbb}"
  # Fixed path, not $XDG_RUNTIME_DIR: this runs both as a systemd user unit and
  # over plain ssh, and the two don't reliably agree on that variable. A lock
  # under a different path is not a lock.
  local LOCK="$HOME/.cache/gord-stats-deploy.lock"
  export MPLBACKEND="${MPLBACKEND:-Agg}"

  # Don't fight a deploy for the repo. This used to test whether
  # gordstats-daily.service was active, which missed the case that actually
  # bit: `pi deploy gord-stats` ssh's in and runs pi-deploy.sh directly, so no
  # unit is ever active and this tick sailed straight into a tree the deploy
  # was rewriting. On 2026-08-29 two ticks died in `jekyll build` with ENOENT
  # on a chart PNG — power.body() clears the section's charts before running
  # the sim that regenerates them, and Jekyll stat'd one inside that window.
  # The checkout below is the same hazard pointed the other way: it would
  # discard pages a deploy was halfway through writing.
  #
  # So both entry points take one lock instead. The deploy waits for a tick;
  # a tick skips rather than waits, which is what it did before and costs
  # nothing — the next one is ten minutes out.
  mkdir -p "$(dirname "$LOCK")"
  exec 9>"$LOCK"
  if ! flock -n 9; then
    log "a deploy holds the lock — skipping this tick"
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

  # Each gate exits 0 (regenerated something) or 3 (nothing to do); anything
  # else is a failure worth the notify unit.
  local WNBA=0 FANTASY=0 CFB=0
  python -m wnba.wnba_live || WNBA=$?
  if [ "$WNBA" -ne 0 ] && [ "$WNBA" -ne 3 ]; then
    echo "❌ WNBA live refresh failed (rc=$WNBA)"
    exit "$WNBA"
  fi
  python -m fantasy.live || FANTASY=$?
  if [ "$FANTASY" -ne 0 ] && [ "$FANTASY" -ne 3 ]; then
    echo "❌ fantasy live refresh failed (rc=$FANTASY)"
    exit "$FANTASY"
  fi
  python -m cfb.live || CFB=$?
  if [ "$CFB" -ne 0 ] && [ "$CFB" -ne 3 ]; then
    echo "❌ CFB live refresh failed (rc=$CFB)"
    exit "$CFB"
  fi
  # College basketball's scoreboard is served by its own Worker, not by a
  # rebuilt page, so its gate pushes and never asks for a build. A failure is
  # reported at the end of the tick rather than stopping the gates that do.
  local CBB=0
  python -m cbb.live || CBB=$?
  [ "$CBB" -ne 0 ] && [ "$CBB" -ne 3 ] && echo "❌ CBB live scoreboard push failed (rc=$CBB)"
  local CBB_RC=0
  [ "$CBB" -ne 0 ] && [ "$CBB" -ne 3 ] && CBB_RC="$CBB"

  if [ "$WNBA" -eq 3 ] && [ "$FANTASY" -eq 3 ] && [ "$CFB" -eq 3 ]; then
    exit "$CBB_RC"               # nothing to rebuild — quiet tick
  fi
  local WHAT=""
  [ "$WNBA" -eq 0 ] && WHAT="wnba"
  [ "$FANTASY" -eq 0 ] && WHAT="${WHAT:+$WHAT,}fantasy"
  [ "$CFB" -eq 0 ] && WHAT="${WHAT:+$WHAT,}cfb"

  ########################################
  # BUILD + PUBLISH
  ########################################
  export PATH="$HOME/.local/share/gem/ruby/3.3.0/bin:$HOME/gems/bin:$PATH"
  export BUNDLE_PATH="vendor/bundle"
  export BUNDLE_WITHOUT="development:test"

  log "jekyll build"
  bundle exec jekyll build --source docs --destination docs/_site --quiet

  log "deploying to Cloudflare Pages ($PROJECT)"
  # The daily run's own time rides along, so the freshness check sees it.
  local DAILY_AT="" DAILY_RC="null"
  if [ -f "$PWD/.last_daily_publish" ]; then
    read -r DAILY_AT DAILY_RC < "$PWD/.last_daily_publish" || true
  fi
  write_status "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$DAILY_AT" "$DAILY_RC"
  publish "$PROJECT" >/dev/null

  ########################################
  # COMMIT: hourly for WNBA, at once for fantasy
  ########################################
  local STAMP="$PWD/.last_live_commit" NOW LAST=0
  NOW=$(date +%s)
  [ -f "$STAMP" ] && LAST=$(stat -c %Y "$STAMP")

  if [ "$FANTASY" -eq 0 ] || [ $((NOW - LAST)) -ge 3600 ]; then
    git add -A docs data
    if git diff --cached --quiet; then
      log "no data changes to record"
    else
      git commit -q -m "Live update ($WHAT) $(date '+%Y-%m-%d %H:%M')"
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
  exit "$CBB_RC"
}

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }

# publish (the upload, retried) and write_status (docs/_site/status.json).
# shellcheck source=deploy/publish.sh
source "$(dirname "${BASH_SOURCE[0]}")/publish.sh"

main "$@"
