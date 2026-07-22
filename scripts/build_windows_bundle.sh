#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist/windows"
STAGE_DIR="$DIST_DIR/SpliceApp-Windows"
ZIP_PATH="$DIST_DIR/SpliceApp-Windows.zip"

echo "Building Windows bundle..."
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"
mkdir -p "$DIST_DIR"

# Copy required app sources/assets for runtime.
rsync -a \
  --exclude '.git/' \
  --exclude '.github/' \
  --exclude '.env' \
  --exclude '.env.*' \
  --exclude '.devcontainer/' \
  --exclude '.vercel/' \
  --exclude '.streamlit/' \
  --exclude '__pycache__/' \
  --exclude '.DS_Store' \
  --exclude 'dist/' \
  --exclude 'graphify-out/' \
  --exclude '_tmp_ispeed_ext/' \
  --exclude 'tests/' \
  "$ROOT_DIR/" "$STAGE_DIR/"

# Ensure expected local-only launch scripts are present and executable within bundle.
chmod +x "$STAGE_DIR/scripts/build_windows_bundle.sh" || true

rm -f "$ZIP_PATH"
(
  cd "$DIST_DIR"
  zip -r "$(basename "$ZIP_PATH")" "$(basename "$STAGE_DIR")" >/dev/null
)

echo "Windows bundle created: $ZIP_PATH"
