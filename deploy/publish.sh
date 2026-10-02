# Sourced by pi-deploy.sh and pi-live.sh: the Cloudflare upload, retried, and
# the status file the freshness check reads. Both callers run from the repo
# root with `set -euo pipefail` and define log().

# wrangler's upload fails now and then on a network blip - "fetch failed", on
# 2026-09-27, after a build that was fine - and nothing retried it: the site
# stayed a run behind until the next timer. Three tries, a pause between.
# Progress goes to stderr, because pi-live.sh silences the upload's stdout.
publish() {
  local project="$1" attempt
  for attempt in 1 2 3; do
    if wrangler pages deploy docs/_site --project-name="$project" --commit-dirty=true; then
      return 0
    fi
    if [ "$attempt" -lt 3 ]; then
      log "Cloudflare upload failed (attempt $attempt of 3) — retrying in $((attempt * 30))s" >&2
      sleep $((attempt * 30))
    fi
  done
  echo "❌ Cloudflare upload failed three times" >&2
  return 1
}

# docs/_site/status.json: when this publish happened, and when the daily run
# last got through, with its sections' exit status (4 = some failed, published
# anyway). deploy/freshness.py reads it off the live site every two hours and
# opens an issue when the daily half goes stale. The live ticks carry the daily
# time forward from .last_daily_publish, so a Sunday of live publishes cannot
# hide a daily run that has stopped.
write_status() {
  local published="$1" daily="$2" rc="$3"
  printf '{"published":"%s","daily":"%s","daily_sections_rc":%s,"commit":"%s"}\n' \
    "$published" "$daily" "${rc:-null}" "$(git rev-parse --short HEAD)" > docs/_site/status.json
}

# `git pull --rebase` that cannot wedge the Pi. A plain rebase first; on a
# conflict, back out and replay the Pi's own commits with `-X theirs` (in a
# rebase, "theirs" is the commits being replayed - the Pi's). Everything the Pi
# commits is generated data under docs/ and data/, so its copy is the one to
# keep. Before this, a rejected push whose rebase conflicted (a parquet file
# both sides had rewritten - they never merge) left the data commit local, and
# every later daily run stopped at its pull and every live tick skipped,
# quietly, until someone cleaned up by hand (the 2026-09-28 audit). Fails only
# if both tries do, backed out either way so the next run starts clean.
# Callers set BRANCH.
pull_rebase() {
  git pull --rebase --quiet origin "$BRANCH" && return 0
  git rebase --abort 2>/dev/null || true
  log "rebase conflicted — replaying this machine's generated data over origin's"
  git pull --rebase --quiet -X theirs origin "$BRANCH" && return 0
  git rebase --abort 2>/dev/null || true
  echo "❌ git pull --rebase conflicted with origin/$BRANCH even preferring local data; backed it out"
  return 1
}

# Exit status for a live tick that could not do its job for a passing reason
# (a network blip, the deploy holding a new dependency): 0 - a skipped tick -
# unless it has been failing for an hour, then 1 so the notify unit mails once
# an hour rather than every ten minutes (a day-long ESPN outage used to be 144
# mails, past Resend's free 100 a day, burying the daily run's own alerts).
# `ok` clears the streak.
tick_trouble() {
  local mark="$PWD/.live_trouble_since" now
  now=$(date +%s)
  if [ "${1:-}" = "ok" ]; then rm -f "$mark"; return 0; fi
  [ -f "$mark" ] || echo "$now" > "$mark"
  local since
  since=$(cat "$mark")
  if [ $((now - since)) -ge 3600 ]; then
    echo "$now" > "$mark"                 # the next mail an hour from now
    return 1
  fi
  return 0
}

# What the Jekyll side was installed from. pi-deploy.sh runs `bundle install`
# and then writes this to GEMS_STAMP; pi-live.sh never installs gems, so it
# compares before building - a Gemfile.lock it pulled that the daily run has
# not installed yet would otherwise fail every tick's build until it had (the
# Python side has had the same stamp, .venv/.requirements-sha256, since the
# 2026-09-28 audit). Relative to the repo root, where both scripts run.
GEMS_STAMP="vendor/bundle/.gems-sha256"
gems_hash() {
  cat Gemfile Gemfile.lock | sha256sum | cut -d' ' -f1
}
