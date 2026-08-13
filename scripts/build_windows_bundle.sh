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

# Copy only files needed to build the Windows executable in production.
copy_path() {
  local source_path="$1"
  rsync -a \
    --exclude '__pycache__/' \
    --exclude '.DS_Store' \
    --exclude '*.db' \
    --exclude '*.db-wal' \
    --exclude '*.db-shm' \
    "$ROOT_DIR/$source_path" "$STAGE_DIR/$(dirname "$source_path")/"
}

mkdir -p "$STAGE_DIR/packaging/windows"

copy_path "app.py"
copy_path "feedback_system.py"
copy_path "requirements.txt"
copy_path "assets"
copy_path "pages"
copy_path "ui"
copy_path "splice"
copy_path "vbom_legacy"
copy_path "scripts/validate_production.py"
copy_path "packaging/windows/build_windows_exe.bat"
copy_path "packaging/windows/run_exe_local.bat"
copy_path "packaging/windows/README_FOR_USERS.txt"
copy_path "packaging/windows/README_WINDOWS_INSTALL.md"
copy_path "packaging/windows/SpliceApp.spec"
copy_path "packaging/windows/streamlit_bootstrap.py"

# The SECR database is per-user engineering history: the kit ships without one
# and the app creates an empty database on first use.
if find "$STAGE_DIR" -name '*.db' -print -quit | grep -q .; then
  echo "ERROR: a database file was staged into the Windows bundle." >&2
  find "$STAGE_DIR" -name '*.db' >&2
  exit 1
fi

rm -f "$ZIP_PATH"
(
  cd "$DIST_DIR"
  zip -r "$(basename "$ZIP_PATH")" "$(basename "$STAGE_DIR")" >/dev/null
)

# A stale checksum beside a fresh zip is worse than none, so regenerate it
# every build.
rm -f "$ZIP_PATH.sha256"
(
  cd "$DIST_DIR"
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$(basename "$ZIP_PATH")" > "$(basename "$ZIP_PATH").sha256"
  else
    sha256sum "$(basename "$ZIP_PATH")" > "$(basename "$ZIP_PATH").sha256"
  fi
)

echo "Windows bundle created: $ZIP_PATH"
echo "SHA-256:               $ZIP_PATH.sha256"
