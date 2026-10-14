#!/usr/bin/env bash
# Start the BRIGHT print + email receiver. Run this on the printing laptop:
#   ./start.sh
# Set SMTP_USER and SMTP_PASS in the local environment before launching.
set -eu
: "${SMTP_USER:?Set SMTP_USER in your local environment}"
: "${SMTP_PASS:?Set SMTP_PASS in your local environment}"
python3 "$(dirname "$0")/print_receiver.py" \
    --dir ~/prints \
    --printer Canon_G500_series_USB \
    --smtp-host smtp.gmail.com \
    --smtp-port 587
