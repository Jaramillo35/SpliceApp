#!/bin/bash
cd "$(dirname "$0")"
echo "Stopping the DTx Compare Tool..."
docker compose down
echo
echo "Done. The tool has been shut down. You can close this window."
