#!/usr/bin/env bash
set -euo pipefail

########################################
# LOAD SECRETS
########################################

ENV_FILE="$HOME/cbb-model/.env"

if [ -f "$ENV_FILE" ]; then
  set -o allexport
  source "$ENV_FILE"
  set +o allexport
else
  echo "ERROR: Secret env file not found at $ENV_FILE"
  exit 1
fi

if [ -z "${RESEND_API:-}" ]; then
  echo "ERROR: RESEND_API not set"
  exit 1
fi

########################################
# EMAIL FUNCTION (RESEND)
########################################

send_email() {
  curl -s -X POST https://api.resend.com/emails \
    -H "Authorization: Bearer $RESEND_API" \
    -H "Content-Type: application/json" \
    -d @- <<EOF
{
  "from": "CBB Deploy <onboarding@resend.dev>",
  "to": "$RESEND_EMAIL",
  "subject": "$1",
  "html": "$2"
}
EOF
}

########################################
# START TIMER + LOG
########################################

START_TIME=$(date +%s)
DEPLOY_LOG=""
trap 'send_email "CBB Deploy FAILED ❌" "<b>Error at line:</b> $LINENO<br><pre>$DEPLOY_LOG</pre>"; exit 1' ERR

########################################
# HOST DETECTION
########################################

HOSTNAME="$(hostname | tr '[:upper:]' '[:lower:]')"

if [[ "$HOSTNAME" == *"pi"* || "$HOSTNAME" == *"raspberry"* ]]; then
  IS_PI=true
else
  IS_PI=false
fi

DEPLOY_LOG+="<b>Host:</b> $HOSTNAME<br>"
DEPLOY_LOG+="<b>Start Time:</b> $(date)<br><br>"

cd "$(git rev-parse --show-toplevel)"

########################################
# GIT PREP
########################################

CURRENT_BRANCH="$(git branch --show-current)"

if [ "$CURRENT_BRANCH" != "main" ]; then
  git checkout main
fi

STASH_CREATED=false

if ! git diff --quiet || ! git diff --cached --quiet || [ -n "$(git ls-files --others --exclude-standard)" ]; then
  git stash push -u -m "auto-deploy-stash-$(date +%s)"
  STASH_CREATED=true
  DEPLOY_LOG+="Local changes stashed.<br>"
fi

git pull --ff-only
LATEST_COMMIT=$(git rev-parse --short HEAD)

DEPLOY_LOG+="<b>Branch:</b> main<br>"
DEPLOY_LOG+="<b>Commit:</b> $LATEST_COMMIT<br><br>"

########################################
# CONDA SETUP
########################################

CONDA_BASE="$HOME/miniconda3"

source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate cbb-env

DEPLOY_LOG+="Conda env: $CONDA_DEFAULT_ENV<br>"

########################################
# DATA GENERATION
########################################
pip install -e . >/dev/null 2>&1
python -m cbb.main
DEPLOY_LOG+="Data generation completed.<br>"

########################################
# BUNDLER SETUP
########################################

export PATH="$HOME/.gem/ruby/3.3.0/bin:$HOME/gems/bin:$PATH"
export BUNDLE_PATH="vendor/bundle"
export BUNDLE_WITHOUT="development:test"

bundle _2.7.2_ install

########################################
# JEKYLL BUILD
########################################

bundle _2.7.2_ exec jekyll clean --source docs --destination docs/_site

JEKYLL_ENV=production bundle _2.7.2_ exec jekyll build \
  --source docs \
  --destination docs/_site

DEPLOY_LOG+="Jekyll build complete.<br>"

########################################
# NODE + WRANGLER
########################################

if ! command -v node >/dev/null 2>&1; then
  echo "Node not found"
  exit 1
fi

if ! command -v wrangler >/dev/null 2>&1; then
  echo "Wrangler not found"
  exit 1
fi

WRANGLER_OUTPUT=$(wrangler pages deploy docs/_site \
  --project-name=gordstats-cbb \
  --commit-dirty=true 2>&1)

DEPLOY_LOG+="<b>Wrangler Output:</b><br><pre>$WRANGLER_OUTPUT</pre><br>"

########################################
# RESTORE STASH
########################################

if $STASH_CREATED; then
  if git stash apply; then
    git stash drop
    DEPLOY_LOG+="Stash reapplied cleanly.<br>"
  else
    DEPLOY_LOG+="⚠️ Stash apply had conflicts — stash preserved.<br>"
  fi
fi

########################################
# COMMIT GENERATED FILES
########################################

git add docs/**/*.html 2>/dev/null || true
git add data/**/*.json 2>/dev/null || true
git add *.json 2>/dev/null || true
git add *.html 2>/dev/null || true

if ! git diff --cached --quiet; then
  git commit -m "Auto-update generated data ($(date '+%Y-%m-%d %H:%M:%S'))"
  git push origin main
  DEPLOY_LOG+="Generated files committed and pushed.<br>"
else
  DEPLOY_LOG+="No generated file changes.<br>"
fi

########################################
# FINISH + EMAIL SUCCESS
########################################

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

DEPLOY_LOG+="<br><b>Duration:</b> ${DURATION}s<br>"
DEPLOY_LOG+="<b>Status:</b> ✅ SUCCESS<br>"

send_email "CBB Deploy Successful ✅" "$DEPLOY_LOG"

echo "Deployment complete!"
