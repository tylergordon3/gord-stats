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

###  Always deploy from main (for now)
CURRENT_BRANCH="$(git branch --show-current)"

if [ "$CURRENT_BRANCH" != "main" ]; then
  echo "Switching to main"
  git checkout main
fi

git pull --ff-only

### HARD-BOOTSTRAP CONDA
CONDA_BASE="$HOME/miniconda3"

if [ ! -f "$CONDA_BASE/etc/profile.d/conda.sh" ]; then
  echo "❌ Conda not found at $CONDA_BASE"
  exit 1
fi

source "$CONDA_BASE/etc/profile.d/conda.sh"

conda activate cbb-env || {
  echo "❌ Conda env 'cbb-env' not found"
  conda env list
  exit 1
}

echo "Conda active: $CONDA_DEFAULT_ENV"

### Run data generation
echo "⚙️ Running data generation..."
python py/main.py

### Make Bundler available (WSL-safe)
export PATH="$HOME/gems/bin:$PATH"

if ! command -v bundle >/dev/null 2>&1; then
  echo "❌ Bundler not found"
  echo "PATH=$PATH"
  exit 1
fi

echo " Bundler: $(which bundle)"

###  Clean Jekyll build
echo " Cleaning old Jekyll build..."
bundle exec jekyll clean \
  --source docs \
  --destination docs/_site

###  Build Jekyll site
echo " Building Jekyll site..."
JEKYLL_ENV=production bundle exec jekyll build \
  --source docs \
  --destination docs/_site

###  Bootstrap Node.js 20 (WSL-safe)
export NVM_DIR="$HOME/.nvm"

if [ -s "$NVM_DIR/nvm.sh" ]; then
  source "$NVM_DIR/nvm.sh"
  nvm use 20
else
  echo "❌ nvm not found; Node 20 required for Wrangler"
  node -v || true
  exit 1
fi

echo " Node version: $(node -v)"

###  Deploy to Cloudflare Pages
echo " Deploying to Cloudflare Pages..."
wrangler pages deploy docs/_site \
  --project-name=gordstats-cbb \
  --commit-dirty=true

echo "✅ Deployment complete!"
