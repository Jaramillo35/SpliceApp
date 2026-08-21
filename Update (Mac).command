#!/bin/bash
cd "$(dirname "$0")"
echo "============================================================"
echo "  Updating the System Engineer Toolkit"
echo
echo "  This gets the latest version and restarts the tool."
echo "  Takes a minute or two. Data is kept."
echo "============================================================"
echo
if ! git pull; then
  echo "Could not download the update. Is this folder a git clone,"
  echo "and is the network/VPN up?"
  read -n 1 -s -r -p "Press any key to close."
  exit 1
fi
if ! docker compose up --build -d; then
  echo "Docker could not rebuild. Is Docker Desktop running?"
  read -n 1 -s -r -p "Press any key to close."
  exit 1
fi
echo
echo "Update done. The tool is running the latest version at:"
echo "        http://localhost:8501"
read -n 1 -s -r -p "Press any key to close."
