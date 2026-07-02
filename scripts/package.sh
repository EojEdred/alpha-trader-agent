#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# ALPHA TRADER PACKAGER SCRIPT
# ═══════════════════════════════════════════════════════════════
# This script:
# 1. Builds the latest React web dashboard assets.
# 2. Automatically copies them to the backend templates directory.
# 3. Creates a clean distribution ZIP excluding all user secrets/credentials.
# ═══════════════════════════════════════════════════════════════

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_PATH="${HOME}/Desktop/alpha-trader-package.zip"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[Packager]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[Packager Warning]${NC} $1"
}

error() {
    echo -e "${RED}[Packager Error]${NC} $1"
    exit 1
}

# 1. Build frontend
log "Building frontend web dashboard..."
cd "${PROJECT_DIR}/web"
if command -v npm &> /dev/null; then
    npm run build
else
    warn "npm is not installed. Skipping frontend rebuild. Using existing build if present."
fi

# 2. Package tracking files only (via git archive to respect gitignore automatically)
log "Packaging application..."
cd "${PROJECT_DIR}"

if [ ! -d ".git" ]; then
    log "Initializing temporary git repo to gather tracked files..."
    git init -q
    git add .
    git commit -q -m "Temporary packaging commit"
    CLEANUP_GIT=true
fi

# Generate the archive
git archive -o "${DIST_PATH}" HEAD

if [ "$CLEANUP_GIT" = true ]; then
    rm -rf .git
    log "Cleaned up temporary git repo."
fi

log "════════════════════════════════════════════════════════"
log "Packaged archive created successfully!"
log "File Location: ${DIST_PATH}"
log "File Size: $(du -sh "${DIST_PATH}" | cut -f1)"
log "════════════════════════════════════════════════════════"
echo "You can now distribute the ZIP file to your users."
