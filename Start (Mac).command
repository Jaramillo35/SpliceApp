#!/bin/bash
cd "$(dirname "$0")"
echo "============================================================"
echo "  Starting the System Engineer Toolkit"
echo
echo "  The FIRST time, this takes a few minutes while it prepares"
echo "  everything. Later times are much faster."
echo
echo "  Keep THIS window open while you use the tool."
echo "============================================================"
echo
if ! docker compose up --build -d; then
  echo
  echo "-----------------------------------------------------------"
  echo "  Something went wrong."
  echo "  Is Docker Desktop open? Look for the whale icon in the"
  echo "  top menu bar. Open Docker Desktop, wait until it says"
  echo "  \"running\", then double-click this file again."
  echo "-----------------------------------------------------------"
  echo
  read -n 1 -s -r -p "Press any key to close this window."
  exit 1
fi
echo
echo "Getting the tool ready..."
sleep 10
open "http://localhost:8501"
echo
echo "The tool is running and should have opened in your web browser."
echo "If it did not, open your browser and type this address:"
echo
echo "        http://localhost:8501"
echo
echo "When you are finished, double-click \"Stop (Mac).command\"."
echo "You can leave this window open in the meantime."
