#!/usr/bin/env bash
set -euo pipefail

profile="${1:-default}"
src="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dest="${HOME}/.hermes/profiles/${profile}/plugins/paperclip-cockpit"

mkdir -p "$(dirname "${dest}")"
rm -rf "${dest}"
mkdir -p "${dest}"

rsync -a \
  --exclude '.git' \
  --exclude '__pycache__' \
  --exclude '.DS_Store' \
  "${src}/" "${dest}/"

echo "Installed paperclip-cockpit to ${dest}"
echo "Enable it with: ${profile} plugins enable paperclip-cockpit"
