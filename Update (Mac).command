#!/bin/bash
cd "$(dirname "$0")"
echo "============================================================"
echo "  Updating the System Engineer Toolkit"
echo
echo "  This gets the latest release and restarts the tool."
echo "  Takes a minute or two. Data is kept."
echo "============================================================"
echo
# Always update from the release branch, whatever branch this clone is on.
if ! git fetch origin main; then
  echo "Could not download the update. Is this folder a git clone,"
  echo "and is the network/VPN up?"
  read -n 1 -s -r -p "Press any key to close."
  exit 1
fi
git checkout -q main && git reset -q --hard origin/main || {
  echo "Could not switch to the latest release. Ask for help and"
  echo "mention the message above."
  read -n 1 -s -r -p "Press any key to close."
  exit 1
}
echo "  Now at version $(git rev-parse --short HEAD)"
echo
export GIT_SHA="$(git rev-parse HEAD)"
export GIT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
export BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
if ! docker compose up --build -d; then
  echo "Docker could not rebuild. Is Docker Desktop running?"
  read -n 1 -s -r -p "Press any key to close."
  exit 1
fi
echo
echo "Update done. The tool is running the latest version at:"
echo "        http://localhost:8504"
echo
echo "Open the Admin page inside the tool to see exactly what changed."
read -n 1 -s -r -p "Press any key to close."
