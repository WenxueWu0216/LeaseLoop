#!/bin/sh
set -e
root="$(git rev-parse --show-toplevel)"
cp "$root/scripts/hooks/commit-msg" "$root/.git/hooks/commit-msg"
chmod +x "$root/.git/hooks/commit-msg"
echo "Installed commit-msg hook."
