#!/usr/bin/env bash
# Refresh gord-stats on the Pi and publish it. Run daily by gordstats-daily.timer,
# and on demand with `pi deploy gord-stats`.
#
# Which sections get refreshed is driven by TASKS in ~/secrets/gord-stats.env
# (default: wnba,fantasy,cfb). Turning on college basketball later is a change to
# that variable plus an implementation in gordstats/daily.py — not a change to
# this script. One job builds the whole site, so two sections can never publish
# inconsistent versions of the shared homepage.
set -euo pipefail

# Body lives in main() because this script git-pulls a newer copy of itself
# partway through, and bash reads scripts lazily by byte offset.
main() {
  cd "$(git rev-parse --show-toplevel)"

  local VENV="$PWD/.venv"
  local TASKS="${TASKS:-wnba,fantasy,cfb,nfl,cbb,cbb_power}"
  local PROJECT="${CF_PAGES_PROJECT:-gordstats-cbb}"
  # Fixed path, not $XDG_RUNTIME_DIR: this runs both as gordstats-daily.service
  # and over plain ssh from `pi deploy`, and the two don't reliably agree on
  # that variable. A lock under a different path is not a lock.
  local LOCK="$HOME/.cache/gord-stats-deploy.lock"
  export MPLBACKEND="${MPLBACKEND:-Agg}"

  ########################################
  # LOCK
  ########################################
  # One writer for docs/ and data/ at a time. pi-live.sh takes the same lock
  # and skips when it can't get it; this side waits, because a deploy asked for
  # by hand should happen. A live tick is a couple of minutes at worst, well
  # inside the unit's TimeoutStartSec.
  mkdir -p "$(dirname "$LOCK")"
  exec 9>"$LOCK"
  if ! flock -w 600 9; then
    echo "❌ a live tick has held the deploy lock for 10 minutes — something is stuck"
    exit 1
  fi

  ########################################
  # SECRETS
  ########################################
  # systemd supplies these via EnvironmentFile=, but the script also runs by
  # hand over ssh, where nothing has loaded them. gordstats.daily reads ESPN_S2/SWID
  # and BALL_DONT_LIE_KEY through python-dotenv; wrangler needs the CF token.
  local SECRETS="$HOME/secrets/gord-stats.env"
  [ -f "$SECRETS" ] || { echo "❌ no secrets at $SECRETS"; exit 1; }
  set -o allexport
  # shellcheck source=/dev/null
  . "$SECRETS"
  set +o allexport
  TASKS="${TASKS:-wnba,fantasy,cfb,nfl,cbb,cbb_power}"

  [ -n "${CLOUDFLARE_API_TOKEN:-}" ] || {
    echo "❌ CLOUDFLARE_API_TOKEN not set — wrangler can't deploy unattended."
    echo "   Create a token with the 'Cloudflare Pages: Edit' permission and"
    echo "   add it to $SECRETS."
    exit 1; }

  ########################################
  # CLEAN SLATE
  ########################################
  # A rebase an earlier run left half-done makes every command below fail
  # ("path is unmerged") on every run until someone backs it out by hand.
  if [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ]; then
    log "backing out a rebase an earlier run left unfinished"
    git rebase --abort
  fi
  # Generated output from an interrupted run would block the rebase. Everything
  # tracked under docs/ and data/ is regenerated, so discarding it costs nothing.
  if ! git diff --quiet -- docs data; then
    log "discarding regenerated files left by an earlier run"
    git checkout -- docs data
  fi
  if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "❌ uncommitted changes outside docs/ and data/ — the Pi is a deploy target"
    git status --short
    exit 1
  fi

  ########################################
  # PULL
  ########################################
  local BRANCH BEFORE AFTER
  BRANCH="$(git branch --show-current)"
  BEFORE="$(git rev-parse HEAD)"
  # A network blip here used to abort the run and leave the site six hours
  # stale; three tries first.
  local tries=0
  until git fetch --quiet origin "$BRANCH"; do
    tries=$((tries + 1))
    [ "$tries" -ge 3 ] && { echo "❌ git fetch failed three times"; exit 1; }
    log "git fetch failed — retrying in 20s"
    sleep 20
  done
  pull_rebase
  AFTER="$(git rev-parse HEAD)"
  [ "$BEFORE" = "$AFTER" ] \
    && log "already at $(git rev-parse --short HEAD)" \
    || log "$(git rev-parse --short "$BEFORE") -> $(git rev-parse --short "$AFTER")"

  ########################################
  # PYTHON
  ########################################
  [ -d "$VENV" ] || { log "creating venv"; python3 -m venv "$VENV"; }
  # shellcheck source=/dev/null
  . "$VENV/bin/activate"

  # Hash-stamped rather than diffed against git, so an install can't be skipped
  # just because this run's pull happened to be a no-op.
  local REQ_HASH STAMP
  REQ_HASH="$(sha256sum pyproject.toml | cut -d' ' -f1)"
  STAMP="$VENV/.requirements-sha256"
  if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$REQ_HASH" ]; then
    log "installing dependencies"
    pip install -q --upgrade pip
    # Runtime deps and the packages themselves both come from pyproject.toml.
    pip install -q -e .            # cbb, cfb, wnba, fantasy, gordstats
    echo "$REQ_HASH" > "$STAMP"
  else
    log "dependencies unchanged"
  fi

  ########################################
  # REFRESH
  ########################################
  # A failed section no longer cancels the deploy. Under `set -e` it used to:
  # one fantasy failure on 2026-09-23 left CFB, NFL and every other section
  # unpublished for the day. The rest of the site now goes out, the data is
  # committed, and the script exits non-zero at the very end so OnFailure
  # still sends the alert.
  log "refreshing sections: $TASKS"
  local SECTIONS_RC=0
  run_sections || SECTIONS_RC=$?

  ########################################
  # JEKYLL
  ########################################
  # Cloudflare Pages is a direct-upload target here, not a git-connected build,
  # so the site has to be built on this machine before it can be uploaded.
  export PATH="$HOME/.local/share/gem/ruby/3.3.0/bin:$HOME/gems/bin:$PATH"
  export BUNDLE_PATH="vendor/bundle"
  export BUNDLE_WITHOUT="development:test"

  command -v bundle >/dev/null || { echo "❌ bundler not on PATH"; exit 1; }

  log "bundle install"
  bundle install --quiet

  log "jekyll build"
  bundle exec jekyll build --source docs --destination docs/_site --quiet

  ########################################
  # PUBLISH
  ########################################
  # Re-check origin first. The pull above is minutes old by now — the refresh,
  # the bundle install and the Jekyll build all sit between them — so a commit
  # pushed inside that window would be published over. Rebuild rather than skip:
  # this run holds the day's fresh data, and the point is to publish both.
  git fetch --quiet origin "$BRANCH"
  if ! git merge-base --is-ancestor "origin/$BRANCH" HEAD; then
    log "origin moved during the build — rebasing and rebuilding before publish"
    git checkout -- docs data       # generated, and regenerated on the next line
    pull_rebase
    SECTIONS_RC=0
    run_sections || SECTIONS_RC=$?
    bundle exec jekyll build --source docs --destination docs/_site --quiet
  fi

  log "deploying to Cloudflare Pages ($PROJECT)"
  local STAMP_AT
  STAMP_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  write_status "$STAMP_AT" "$STAMP_AT" "$SECTIONS_RC"
  publish "$PROJECT"
  printf '%s %s\n' "$STAMP_AT" "$SECTIONS_RC" > "$PWD/.last_daily_publish"

  ########################################
  # COMMIT GENERATED DATA
  ########################################
  # Publishing already happened above, with wrangler — git is not in the
  # publish path. What is recorded here is the refreshed *data*: the archives
  # that are the only record of what the page said, and the caches the next
  # build reads. The generated pages and charts are gitignored, because
  # committing them cost about 100 MB of history a month (one 4 MB page
  # rewritten 422 times in 30 days) purely so the PC could read them.
  # The PC uses `pi pull-site` for that instead.
  git add -A docs data

  if git diff --cached --quiet; then
    log "no data changes to record"
  else
    git commit -q -m "Daily refresh ($TASKS) $(date '+%Y-%m-%d %H:%M')"
    if ! git push --quiet origin "$BRANCH" 2>/dev/null; then
      log "push rejected — rebasing onto origin and retrying"
      pull_rebase
      git push --quiet origin "$BRANCH"
    fi
    log "recorded $(git rev-parse --short HEAD)"
  fi

  if [ "$SECTIONS_RC" -ne 0 ]; then
    echo "❌ published, but a section failed (see FAILED: above) — its pages may be stale"
    exit "$SECTIONS_RC"
  fi
  log "✅ done"
}

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }

# publish (the upload, retried) and write_status (docs/_site/status.json).
# shellcheck source=deploy/publish.sh
source "$(dirname "${BASH_SOURCE[0]}")/publish.sh"

# pull_rebase comes from publish.sh (shared with pi-live.sh).

# Refresh the sections. Returns 0, or 4 (gordstats.daily.SECTIONS_FAILED) when
# some sections failed but the run finished — the homepage rendered and every
# other section wrote its pages, so the caller publishes anyway. Any other
# status is the runner itself breaking (render_home raising, say): the tree
# can't be trusted, so this exits instead of returning. Callers use it in an
# `||`, where `set -e` is off, so every status is handled explicitly here.
run_sections() {
  local rc=0
  python -m gordstats.daily --tasks "$TASKS" || rc=$?
  case "$rc" in
    0 | 4) return "$rc" ;;
    *)
      echo "❌ gordstats.daily exited $rc — not publishing a half-built site"
      exit "$rc"
      ;;
  esac
}

main "$@"
