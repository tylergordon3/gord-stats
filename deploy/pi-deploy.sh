#!/usr/bin/env bash
# Refresh gord-stats on the Pi and publish it. Run daily by gordstats-daily.timer,
# and on demand with `pi deploy gord-stats`.
#
# Which sections get refreshed is driven by TASKS in ~/secrets/gord-stats.env
# (default: wnba,fantasy). Turning on college basketball later is a change to
# that variable plus an implementation in gordstats/daily.py — not a change to
# this script. One job builds the whole site, so two sections can never publish
# inconsistent versions of the shared homepage.
set -euo pipefail

# Body lives in main() because this script git-pulls a newer copy of itself
# partway through, and bash reads scripts lazily by byte offset.
main() {
  cd "$(git rev-parse --show-toplevel)"

  local VENV="$PWD/.venv"
  local TASKS="${TASKS:-wnba,fantasy}"
  local PROJECT="${CF_PAGES_PROJECT:-gordstats-cbb}"
  export MPLBACKEND="${MPLBACKEND:-Agg}"

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
  TASKS="${TASKS:-wnba,fantasy}"

  [ -n "${CLOUDFLARE_API_TOKEN:-}" ] || {
    echo "❌ CLOUDFLARE_API_TOKEN not set — wrangler can't deploy unattended."
    echo "   Create a token with the 'Cloudflare Pages: Edit' permission and"
    echo "   add it to $SECRETS."
    exit 1; }

  ########################################
  # CLEAN SLATE
  ########################################
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
  git fetch --quiet origin "$BRANCH"
  git pull --rebase --quiet origin "$BRANCH"
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
  REQ_HASH="$(cat requirements-pi.txt pyproject.toml | sha256sum | cut -d' ' -f1)"
  STAMP="$VENV/.requirements-sha256"
  if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$REQ_HASH" ]; then
    log "installing dependencies"
    pip install -q --upgrade pip
    pip install -q -r requirements-pi.txt
    pip install -q -e .            # cbb, wnba, fantasy, gordstats
    echo "$REQ_HASH" > "$STAMP"
  else
    log "dependencies unchanged"
  fi

  ########################################
  # REFRESH
  ########################################
  log "refreshing sections: $TASKS"
  python -m gordstats.daily --tasks "$TASKS"

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
    git pull --rebase --quiet origin "$BRANCH"
    python -m gordstats.daily --tasks "$TASKS"
    bundle exec jekyll build --source docs --destination docs/_site --quiet
  fi

  log "deploying to Cloudflare Pages ($PROJECT)"
  wrangler pages deploy docs/_site --project-name="$PROJECT" --commit-dirty=true

  ########################################
  # COMMIT GENERATED DATA
  ########################################
  # docs/_site is gitignored, so this records the refreshed source data and
  # pages, not the build output. Publishing already happened above — this is
  # so the laptop can pull down what the Pi generated.
  git add -A docs data

  if git diff --cached --quiet; then
    log "no data changes to record"
  else
    git commit -q -m "Daily refresh ($TASKS) $(date '+%Y-%m-%d %H:%M')"
    if ! git push --quiet origin "$BRANCH" 2>/dev/null; then
      log "push rejected — rebasing onto origin and retrying"
      git pull --rebase --quiet origin "$BRANCH"
      git push --quiet origin "$BRANCH"
    fi
    log "recorded $(git rev-parse --short HEAD)"
  fi

  log "✅ done"
}

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }

main "$@"
