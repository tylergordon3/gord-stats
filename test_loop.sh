#!/usr/bin/env bash
set -euo pipefail

LOG="$HOME/cbb-model/deploy_test.log"

echo "Starting overnight deploy test at $(date)" | tee -a "$LOG"

while true; do
  echo "----------------------------------------" | tee -a "$LOG"
  echo "Run started at $(date)" | tee -a "$LOG"

  ./deploy_pi.sh >> "$LOG" 2>&1 || {
    echo "Deploy FAILED at $(date)" | tee -a "$LOG"
  }

  echo "Run finished at $(date)" | tee -a "$LOG"
  echo "Sleeping for 1 hour..." | tee -a "$LOG"

  sleep 3600
done
