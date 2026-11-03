#!/bin/zsh
# Future launchd wrapper. It records only a fixed status in the local OS log;
# it does not deliver an external alert or authorize restoration.
set -u
if [[ "$#" != 5 ]]; then
  /usr/bin/logger -t asb-privacy-witness 'ALERT: observer settings incomplete'
  exit 1
fi
if "$1" "$2" --execute --receipt-file "$3" --public-key-file "$4" --trusted-reference-file "$5" >/dev/null 2>&1; then
  /usr/bin/logger -t asb-privacy-witness 'Signed observation valid; source reachability unverified; restore not authorized'
else
  /usr/bin/logger -t asb-privacy-witness 'ALERT: signed observation unavailable, stale, or mismatched; restore not authorized'
  exit 1
fi
