#!/usr/bin/env bash
set -euo pipefail

HOSTNAME="$(hostname | tr '[:upper:]' '[:lower:]')"

if [[ "$HOSTNAME" == *"pi"* || "$HOSTNAME" == *"raspberry"* ]]; then
  IS_PI=true
else
  IS_PI=false
fi

echo "Host: $HOSTNAME"
echo "Raspberry Pi: $IS_PI"

# Always run from repo root
cd "$(dirname "$0")"

### Always deploy from main (for now)
CURRENT_BRANCH="$(git branch --show-current)"

if [ "$CURRENT_BRANCH" != "main" ]; then
  echo "Switching to main"
  git checkout main
fi

### STASH LOCAL CHANGES (if any)
STASH_CREATED=false

if ! git diff --quiet || ! git diff --cached --quiet || [ -n "$(git ls-files --others --exclude-standard)" ]; then
  echo "Local changes detected. Stashing..."
  git stash push -u -m "auto-deploy-stash-$(date +%s)"
  STASH_CREATED=true
else
  echo "No local changes to stash."
fi

git pull --ff-only

### HARD-BOOTSTRAP CONDA
CONDA_BASE="$HOME/miniconda3"

if [ ! -f "$CONDA_BASE/etc/profile.d/conda.sh" ]; then
  echo "ERROR: Conda not found at $CONDA_BASE"
  exit 1
fi

source "$CONDA_BASE/etc/profile.d/conda.sh"

conda activate cbb-env || {
  echo "ERROR: Conda env 'cbb-env' not found"
  conda env list
  exit 1
}

echo "Conda active: $CONDA_DEFAULT_ENV"

### Run data generation
echo "Running data generation..."
python py/main.py

### Bundler setup (Pi vs Computer aware)

if $IS_PI; then
  export PATH="$HOME/.gem/ruby/3.3.0/bin:$PATH"
else
  export PATH="$HOME/gems/bin:$PATH"
fi

# Always allow both (harmless if missing)
export PATH="$HOME/.gem/ruby/3.3.0/bin:$HOME/gems/bin:$PATH"

# Ensure project-local gems
export BUNDLE_PATH="vendor/bundle"
export BUNDLE_WITHOUT="development:test"

# Sanity check
if ! command -v bundle >/dev/null 2>&1; then
  echo "ERROR: Bundler not found"
  echo "PATH=$PATH"
  exit 1
fi

echo "Bundler path: $(which bundle)"
echo "Bundler version: $(bundle -v)"

# Ensure correct Bundler version for lockfile
bundle _2.7.2_ install

### Clean Jekyll build
echo "Cleaning old Jekyll build..."
bundle _2.7.2_ exec jekyll clean \
  --source docs \
  --destination docs/_site

### Build Jekyll site
echo "Building Jekyll site..."
JEKYLL_ENV=production bundle _2.7.2_ exec jekyll build \
  --source docs \
  --destination docs/_site

### Node.js / Wrangler setup

if $IS_PI; then
  # Raspberry Pi: use system-installed Node
  if ! command -v node >/dev/null 2>&1; then
    echo "ERROR: Node.js not found on Raspberry Pi"
    exit 1
  fi
else
  # Desktop / WSL: use nvm if available
  export NVM_DIR="$HOME/.nvm"
  if [ -s "$NVM_DIR/nvm.sh" ]; then
    source "$NVM_DIR/nvm.sh"
    nvm use 20
  else
    echo "ERROR: nvm not found on non-Pi system"
    exit 1
  fi
fi

echo "Node version: $(node -v)"

# Verify Wrangler
if ! command -v wrangler >/dev/null 2>&1; then
  echo "ERROR: wrangler not found"
  exit 1
fi

echo "Node version: $(node -v)"

### Deploy to Cloudflare Pages
echo "Deploying to Cloudflare Pages..."
wrangler pages deploy docs/_site \
  --project-name=gordstats-cbb \
  --commit-dirty=true

echo "Deployment complete!"

### RESTORE STASH (if one was created)

if $STASH_CREATED; then
  echo "Restoring stashed changes..."
  git stash pop || {
    echo "WARNING: Stash pop had conflicts. Please resolve manually."
  }
fi

### Commit generated JSON + HTML only

echo "Committing generated data files..."

# Add only JSON + HTML changes
git add docs/**/*.html 2>/dev/null || true
git add data/**/*.json 2>/dev/null || true
git add *.json 2>/dev/null || true
git add *.html 2>/dev/null || true

# Only commit if there are staged changes
if ! git diff --cached --quiet; then
  git commit -m "Auto-update generated data ($(date '+%Y-%m-%d %H:%M:%S'))"
  git push origin main
  echo "Generated files committed and pushed."
else
  echo "No generated file changes to commit."
fi