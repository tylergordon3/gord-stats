#!/usr/bin/env bash
set -e

### 🐍 Activate Conda environment
if command -v conda >/dev/null 2>&1; then
  echo "🐍 Activating Conda environment: cbb-env"
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate cbb-env
else
  echo "❌ Conda not found. Aborting."
  exit 1
fi

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

echo "🚀 Deploying to Cloudflare Pages..."
wrangler pages deploy docs/_site \
  --project-name=gordstats-cbb \
  --commit-dirty=true

echo "✅ Deployment complete!"
