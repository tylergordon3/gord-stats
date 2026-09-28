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
