#!/usr/bin/env bash
set -e

HOSTNAME="$(hostname | tr '[:upper:]' '[:lower:]')"

if [[ "$HOSTNAME" == *"pi"* || "$HOSTNAME" == *"raspberry"* ]]; then
  IS_PI=true
  TARGET_BRANCH="pi-generated"
else
  IS_PI=false
  TARGET_BRANCH="main"
fi

echo "🖥️ Host: $HOSTNAME"
echo "🌱 Target branch: $TARGET_BRANCH"

# Always run from repo root
cd "$(dirname "$0")"

# Ensure correct git branch
CURRENT_BRANCH="$(git branch --show-current)"

if [ "$CURRENT_BRANCH" != "$TARGET_BRANCH" ]; then
  echo "🔁 Switching to $TARGET_BRANCH"
  git checkout "$TARGET_BRANCH"
fi

### 🐍 HARD-BOOTSTRAP CONDA (no PATH required)
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

echo "🐍 Conda active: $CONDA_DEFAULT_ENV"

### 💎 Make Bundler available (WSL-safe)
export PATH="$HOME/gems/bin:$PATH"

# Sanity check
if ! command -v bundle >/dev/null 2>&1; then
  echo "❌ Bundler not found even after PATH fix"
  echo "PATH=$PATH"
  exit 1
fi

echo "📦 Using bundler: $(which bundle)"

echo "🐍 Running data generation..."
python py/main.py

echo "🧹 Cleaning old Jekyll build..."
bundle exec jekyll clean \
  --source docs \
  --destination docs/_site

echo "🔨 Building Jekyll site..."
JEKYLL_ENV=production bundle exec jekyll build \
  --source docs \
  --destination docs/_site

### 🟩 Bootstrap Node.js 20 (WSL-safe)
export NVM_DIR="$HOME/.nvm"

if [ -s "$NVM_DIR/nvm.sh" ]; then
  source "$NVM_DIR/nvm.sh"
  nvm use 20
else
  echo "❌ nvm not found; Node 20 required for Wrangler"
  node -v || true
  exit 1
fi

echo "🟩 Node version: $(node -v)"

echo "🚀 Deploying to Cloudflare Pages..."
wrangler pages deploy docs/_site \
  --project-name=gordstats-cbb \
  --commit-dirty=true

echo "✅ Deployment complete!"
