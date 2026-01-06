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

# Ensure project-
